"""Google provider boundary; report mirror may conditionally patch description only."""

import asyncio
import json
import logging
import math
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from types import SimpleNamespace

import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from oauthlib.oauth2 import OAuth2Error

from hub.accounting_mirrors.provider import GoogleSheetsHttpMixin
from hub.core.config import Settings
from hub.google_calendar.types import (
    EVENT_SCOPE,
    REPORT_WRITE_SCOPE,
    SCOPE,
    SHEETS_SCOPE,
    Authorization,
    DiscoveredCalendar,
    ProviderError,
    TokenGrant,
)

TIMEOUT = (5, 15)


async def _thread_call(function, *args):
    # Cancelling an await cannot stop requests in a worker thread. Keep the
    # enclosing lifecycle guard until the bounded call actually finishes.
    task = asyncio.create_task(asyncio.to_thread(function, *args))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        try:
            await task
        except Exception:
            pass
        raise


class GoogleCalendarProvider(GoogleSheetsHttpMixin):
    def __init__(self, settings: Settings):
        self.settings = settings
        # These libraries can log request bodies/headers at DEBUG, including credentials.
        for name in ("oauthlib", "requests_oauthlib", "google", "urllib3"):
            logger = logging.getLogger(name)
            logger.disabled = True
            logger.propagate = False
            logger.handlers = [logging.NullHandler()]
            for child in list(logging.Logger.manager.loggerDict):
                if child.startswith(name + "."):
                    logging.getLogger(child).disabled = True

    def _flow(
        self, verifier=None, event_access=False, sheets_access=False, report_write_access=False
    ):
        settings = self.settings
        flow = Flow.from_client_config(
            {
                "web": {
                    "client_id": settings.google_client_id,
                    "client_secret": settings.google_client_secret.get_secret_value(),
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                }
            },
            scopes=[
                SCOPE,
                *([EVENT_SCOPE] if event_access else []),
                *([SHEETS_SCOPE] if sheets_access else []),
                *([REPORT_WRITE_SCOPE] if report_write_access else []),
            ],
            redirect_uri=settings.google_oauth_redirect_uri,
            code_verifier=verifier,
            autogenerate_code_verifier=verifier is None,
        )
        flow.oauth2session.trust_env = False
        return flow

    def build_authorization_url(
        self, state, event_access=False, sheets_access=False, report_write_access=False
    ):
        flow = self._flow(
            event_access=event_access,
            sheets_access=sheets_access,
            report_write_access=report_write_access,
        )
        try:
            url, _ = flow.authorization_url(
                state=state,
                access_type="offline",
                prompt="consent select_account",
                include_granted_scopes="true",
            )
            return Authorization(url, flow.code_verifier)
        finally:
            flow.oauth2session.close()

    async def exchange_authorization_code(
        self, code, verifier, event_access=False, sheets_access=False, report_write_access=False
    ):
        def exchange():
            flow = self._flow(
                verifier,
                event_access=event_access,
                sheets_access=sheets_access,
                report_write_access=report_write_access,
            )
            try:
                try:
                    token = flow.fetch_token(code=code, timeout=TIMEOUT, allow_redirects=False)
                except Warning as changed_scope:
                    # OAuthlib signals incremental grants with a validated token on the warning.
                    # Accept only that documented shape, then enforce our required scope below.
                    token = getattr(changed_scope, "token", None)
                    if not isinstance(token, dict):
                        raise ProviderError("SCOPE_REQUIRED") from None
                scopes = token.get(
                    "scope",
                    [
                        SCOPE,
                        *([EVENT_SCOPE] if event_access else []),
                        *([SHEETS_SCOPE] if sheets_access else []),
                        *([REPORT_WRITE_SCOPE] if report_write_access else []),
                    ],
                )
                if isinstance(scopes, str):
                    scopes = scopes.split()
                if SCOPE not in scopes:
                    raise ProviderError("SCOPE_REQUIRED")
                access = token.get("access_token")
                if not isinstance(access, str) or not access:
                    raise ProviderError("MALFORMED_RESPONSE")
                return TokenGrant(access, token.get("refresh_token"), tuple(scopes))
            except OAuth2Error as exc:
                raise ProviderError(
                    "REAUTH_REQUIRED"
                    if exc.error in {"invalid_grant", "access_denied"}
                    else "CONFIGURATION_ERROR"
                ) from None
            except (requests.RequestException, Warning):
                raise ProviderError("PROVIDER_TEMPORARY_ERROR") from None
            finally:
                flow.oauth2session.close()

        return await _thread_call(exchange)

    async def refresh_credentials(self, refresh_token, scopes=(SCOPE,)):
        def refresh():
            settings = self.settings
            credentials = Credentials(
                None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret.get_secret_value(),
                scopes=list(scopes),
            )
            with requests.Session() as session:
                session.trust_env = False
                transport = Request(session=session)

                def bounded(*args, **kwargs):
                    kwargs["timeout"] = TIMEOUT
                    kwargs["allow_redirects"] = False
                    response = transport(*args, **kwargs)
                    if response.status in {403, 429} or 300 <= response.status < 400:
                        self._check(
                            SimpleNamespace(
                                status_code=response.status,
                                headers=response.headers,
                                json=lambda: json.loads(response.data),
                            )
                        )
                    return response

                try:
                    credentials.refresh(bounded)
                    if (
                        credentials.granted_scopes is not None
                        and SCOPE not in credentials.granted_scopes
                    ):
                        raise ProviderError("SCOPE_REQUIRED")
                    return TokenGrant(
                        credentials.token,
                        credentials.refresh_token,
                        tuple(
                            scopes
                            if credentials.granted_scopes is None
                            else credentials.granted_scopes
                        ),
                    )
                except RefreshError as exc:
                    # Inspect only the machine code, never format/log the exception.
                    payload = (
                        exc.args[1] if len(exc.args) > 1 and isinstance(exc.args[1], dict) else {}
                    )
                    code = payload.get("error")
                    raise ProviderError(
                        "REAUTH_REQUIRED"
                        if code == "invalid_grant"
                        else "CONFIGURATION_ERROR"
                        if code == "invalid_client"
                        else "PROVIDER_TEMPORARY_ERROR"
                    ) from None
                except requests.RequestException:
                    raise ProviderError("PROVIDER_TEMPORARY_ERROR") from None

        return await _thread_call(refresh)

    @staticmethod
    def _check(response):
        status = response.status_code
        if 200 <= status < 300:
            return
        if status == 401:
            raise ProviderError("REAUTH_REQUIRED")
        quota = False
        if status == 403:
            try:
                body = response.json()
                reasons = [
                    item.get("reason")
                    for item in body.get("error", {}).get("errors", [])
                    if isinstance(item, dict)
                ]
                quota = any(
                    reason in {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}
                    for reason in reasons
                )
            except (ValueError, AttributeError, TypeError):
                pass
            if not quota:
                raise ProviderError("SCOPE_REQUIRED")
        if status == 429 or quota:
            value = response.headers.get("Retry-After", "60")
            try:
                seconds = int(value)
            except (ValueError, TypeError):
                try:
                    seconds = math.ceil(
                        (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
                    )
                except (ValueError, TypeError, OverflowError):
                    seconds = 60
            raise ProviderError("RATE_LIMITED", seconds)
        raise ProviderError("PROVIDER_TEMPORARY_ERROR")

    async def list_calendars(self, access_token):
        return await _thread_call(self._list, access_token)

    def _list(self, access_token):
        found = {}
        seen_pages = set()
        page = None
        with requests.Session() as session:
            session.trust_env = False
            for _ in range(1000):
                params = {"maxResults": 250, "showHidden": "true", "showDeleted": "false"}
                if page:
                    params["pageToken"] = page
                try:
                    response = session.get(
                        "https://www.googleapis.com/calendar/v3/users/me/calendarList",
                        params=params,
                        headers={"Authorization": "Bearer " + access_token},
                        timeout=TIMEOUT,
                        allow_redirects=False,
                    )
                    self._check(response)
                    body = response.json()
                except (requests.RequestException, ValueError):
                    raise ProviderError("PROVIDER_TEMPORARY_ERROR") from None
                if (
                    not isinstance(body, dict)
                    or not isinstance(body.get("items", []), list)
                    or ("items" not in body and body.get("kind") != "calendar#calendarList")
                ):
                    raise ProviderError("MALFORMED_RESPONSE")
                for item in body.get("items", []):
                    value = self._normalize(item)
                    if value.provider_id in found and found[value.provider_id] != value:
                        raise ProviderError("MALFORMED_RESPONSE")
                    found[value.provider_id] = value
                page = body.get("nextPageToken")
                if page is None:
                    return list(found.values())
                if not isinstance(page, str) or not page or len(page) > 4096 or page in seen_pages:
                    raise ProviderError("MALFORMED_RESPONSE")
                seen_pages.add(page)
        raise ProviderError("MALFORMED_RESPONSE")

    @staticmethod
    def _normalize(item):
        if not isinstance(item, dict):
            raise ProviderError("MALFORMED_RESPONSE")
        identifier, name = item.get("id"), item.get("summary")
        timezone, primary = item.get("timeZone"), item.get("primary", False)
        role = item.get("accessRole")
        if (
            not isinstance(identifier, str)
            or not identifier
            or len(identifier) > 1024
            or any(ord(c) < 32 for c in identifier)
            or not isinstance(name, str)
            or not name.strip()
            or (timezone is not None and (not isinstance(timezone, str) or len(timezone) > 100))
            or not isinstance(primary, bool)
            or role not in {"freeBusyReader", "reader", "writer", "owner"}
        ):
            raise ProviderError("MALFORMED_RESPONSE")
        name = "".join(c for c in name if ord(c) >= 32).strip()[:150]
        if not name or (timezone and "\x00" in timezone):
            raise ProviderError("MALFORMED_RESPONSE")
        return DiscoveredCalendar(identifier, name, timezone, primary, role)

    async def revoke_credentials(self, refresh_token):
        def revoke():
            try:
                with requests.Session() as session:
                    session.trust_env = False
                    response = session.post(
                        "https://oauth2.googleapis.com/revoke",
                        data={"token": refresh_token},
                        timeout=TIMEOUT,
                        allow_redirects=False,
                    )
                    if response.status_code == 400:
                        try:
                            if response.json().get("error") == "invalid_token":
                                return  # Already revoked is idempotent.
                        except (ValueError, AttributeError):
                            pass
                    self._check(response)
            except requests.RequestException:
                raise ProviderError("PROVIDER_TEMPORARY_ERROR") from None

        await _thread_call(revoke)

    async def list_events(self, access_token, provider_calendar_id, time_min, time_max, timezone):
        return await _thread_call(
            self._events, access_token, provider_calendar_id, time_min, time_max, timezone
        )

    def _events(self, access_token, provider_calendar_id, time_min, time_max, timezone):
        from time import monotonic
        from urllib.parse import quote

        from hub.calendar_events.normalization import normalize_event, recurrence_identity

        found, instances, seen_pages, statuses = {}, {}, set(), {}
        page, received, started = None, 0, monotonic()
        with requests.Session() as session:
            session.trust_env = False
            for _ in range(100):
                if monotonic() - started > 45:
                    raise ProviderError("REQUEST_LIMIT")
                params = {
                    "maxResults": 250,
                    "singleEvents": "true",
                    "orderBy": "startTime",
                    "showDeleted": "false",
                    "timeMin": time_min.isoformat(),
                    "timeMax": time_max.isoformat(),
                    "timeZone": timezone,
                    "fields": (
                        "kind,timeZone,nextPageToken,items(id,status,summary,description,"
                        "location,start,end,htmlLink,recurringEventId,originalStartTime,updated)"
                    ),
                }
                if page:
                    params["pageToken"] = page
                try:
                    with session.get(
                        "https://www.googleapis.com/calendar/v3/calendars/"
                        + quote(provider_calendar_id, safe="")
                        + "/events",
                        params=params,
                        headers={"Authorization": "Bearer " + access_token},
                        timeout=TIMEOUT,
                        allow_redirects=False,
                        stream=True,
                    ) as response:
                        # Bound the full read, including error bodies, before parsing JSON.
                        chunks = []
                        for chunk in response.iter_content(65536):
                            received += len(chunk)
                            if received > 8_000_000 or monotonic() - started > 45:
                                raise ProviderError("REQUEST_LIMIT")
                            chunks.append(chunk)
                        raw = b"".join(chunks)

                        def body_json(raw=raw):
                            return json.loads(raw)

                        try:
                            self._check(
                                SimpleNamespace(
                                    status_code=response.status_code,
                                    headers=response.headers,
                                    json=body_json,
                                )
                            )
                        except ProviderError as exc:
                            if exc.code == "SCOPE_REQUIRED":
                                # A calendar ACL denial isn't necessarily missing OAuth scope.
                                reasons = []
                                try:
                                    reasons = [
                                        x.get("reason")
                                        for x in body_json().get("error", {}).get("errors", [])
                                    ]
                                except (ValueError, TypeError, AttributeError):
                                    pass
                                raise ProviderError(
                                    "EVENT_SCOPE_REQUIRED"
                                    if "insufficientPermissions" in reasons
                                    else "CALENDAR_UNAVAILABLE"
                                ) from None
                            if response.status_code == 404:
                                raise ProviderError("CALENDAR_UNAVAILABLE") from None
                            raise
                        body = body_json()
                except requests.RequestException:
                    raise ProviderError("PROVIDER_TEMPORARY_ERROR") from None
                except ValueError:
                    raise ProviderError("MALFORMED_RESPONSE") from None
                if (
                    not isinstance(body, dict)
                    or not isinstance(body.get("items", []), list)
                    or ("items" not in body and body.get("kind") != "calendar#events")
                ):
                    raise ProviderError("MALFORMED_RESPONSE")
                for item in body.get("items", []):
                    event = normalize_event(item, timezone)
                    identifier = item["id"]
                    event_status = item.get("status", "confirmed")
                    if identifier in statuses and statuses[identifier] != event_status:
                        raise ProviderError("MALFORMED_RESPONSE")
                    statuses[identifier] = event_status
                    key = recurrence_identity(item, timezone)
                    if key is not None:
                        representation = (identifier, event_status, event)
                        if key in instances and instances[key] != representation:
                            raise ProviderError("MALFORMED_RESPONSE")
                        instances[key] = representation
                    if event is None:
                        continue
                    if event.provider_event_id in found and found[event.provider_event_id] != event:
                        raise ProviderError("MALFORMED_RESPONSE")
                    found[event.provider_event_id] = event
                    if len(found) > 10000:
                        raise ProviderError("REQUEST_LIMIT")
                page = body.get("nextPageToken")
                if page is None:
                    return list(found.values())
                if not isinstance(page, str) or not page or len(page) > 4096 or page in seen_pages:
                    raise ProviderError("MALFORMED_RESPONSE")
                seen_pages.add(page)
        raise ProviderError("REQUEST_LIMIT")

    async def get_report_event(self, access_token, calendar_id, event_id):
        return await _thread_call(self._report_event, access_token, calendar_id, event_id)

    async def patch_report_description(
        self, access_token, calendar_id, event_id, etag, description
    ):
        return await _thread_call(
            self._report_event, access_token, calendar_id, event_id, etag, description
        )

    def _report_event(self, access_token, calendar_id, event_id, etag=None, description=None):
        from urllib.parse import quote

        url = (
            "https://www.googleapis.com/calendar/v3/calendars/"
            + quote(calendar_id, safe="")
            + "/events/"
            + quote(event_id, safe="")
        )
        headers = {"Authorization": "Bearer " + access_token}
        with requests.Session() as session:
            session.trust_env = False
            try:
                if etag is None:
                    response = session.get(
                        url, headers=headers, timeout=TIMEOUT, allow_redirects=False
                    )
                else:
                    headers["If-Match"] = etag
                    response = session.patch(
                        url,
                        headers=headers,
                        json={"description": description},
                        params={"sendUpdates": "none"},
                        timeout=TIMEOUT,
                        allow_redirects=False,
                    )
                if response.status_code == 412:
                    raise ProviderError("EVENT_CHANGED")
                if response.status_code in {404, 410}:
                    raise ProviderError("CALENDAR_UNAVAILABLE")
                self._check(response)
                result = response.json()
                if not isinstance(result, dict) or result.get("id") != event_id:
                    raise ProviderError("MALFORMED_RESPONSE")
                return result
            except (requests.RequestException, ValueError):
                raise ProviderError("PROVIDER_TEMPORARY_ERROR") from None
