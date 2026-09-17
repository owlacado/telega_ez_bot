"""The sole Google network boundary. No event API and no calendar deletion API."""

import asyncio
import logging
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

import requests
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from oauthlib.oauth2 import OAuth2Error

from hub.core.config import Settings
from hub.google_calendar.types import (
    SCOPE,
    Authorization,
    DiscoveredCalendar,
    ProviderError,
    TokenGrant,
)

TIMEOUT = (5, 15)


class GoogleCalendarProvider:
    def __init__(self, settings: Settings):
        self.settings = settings
        # These libraries can log request bodies/headers at DEBUG, including credentials.
        for name in ("oauthlib", "requests_oauthlib", "google.auth", "urllib3"):
            logging.getLogger(name).disabled = True
            for child in list(logging.Logger.manager.loggerDict):
                if child.startswith(name + "."):
                    logging.getLogger(child).disabled = True

    def _flow(self, verifier=None):
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
            scopes=[SCOPE],
            redirect_uri=settings.google_oauth_redirect_uri,
            code_verifier=verifier,
            autogenerate_code_verifier=verifier is None,
        )
        flow.oauth2session.trust_env = False
        return flow

    def build_authorization_url(self, state):
        flow = self._flow()
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

    async def exchange_authorization_code(self, code, verifier):
        def exchange():
            flow = self._flow(verifier)
            try:
                try:
                    token = flow.fetch_token(code=code, timeout=TIMEOUT, allow_redirects=False)
                except Warning as changed_scope:
                    # OAuthlib signals incremental grants with a validated token on the warning.
                    # Accept only that documented shape, then enforce our required scope below.
                    token = getattr(changed_scope, "token", None)
                    if not isinstance(token, dict):
                        raise ProviderError("SCOPE_REQUIRED") from None
                scopes = token.get("scope", [SCOPE])
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

        return await asyncio.to_thread(exchange)

    async def refresh_credentials(self, refresh_token):
        def refresh():
            settings = self.settings
            credentials = Credentials(
                None,
                refresh_token=refresh_token,
                token_uri="https://oauth2.googleapis.com/token",
                client_id=settings.google_client_id,
                client_secret=settings.google_client_secret.get_secret_value(),
                scopes=[SCOPE],
            )
            with requests.Session() as session:
                session.trust_env = False
                transport = Request(session=session)

                def bounded(*args, **kwargs):
                    kwargs["timeout"] = TIMEOUT
                    return transport(*args, **kwargs)

                try:
                    credentials.refresh(bounded)
                    if credentials.granted_scopes and SCOPE not in credentials.granted_scopes:
                        raise ProviderError("SCOPE_REQUIRED")
                    return TokenGrant(
                        credentials.token,
                        credentials.refresh_token,
                        tuple(credentials.granted_scopes or [SCOPE]),
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

        return await asyncio.to_thread(refresh)

    @staticmethod
    def _check(response):
        status = response.status_code
        if 200 <= status < 300:
            return
        if status == 401:
            raise ProviderError("REAUTH_REQUIRED")
        if status == 403:
            raise ProviderError("SCOPE_REQUIRED")
        if status == 429:
            value = response.headers.get("Retry-After", "60")
            try:
                seconds = int(value)
            except (ValueError, TypeError):
                try:
                    seconds = int(
                        (parsedate_to_datetime(value) - datetime.now(UTC)).total_seconds()
                    )
                except (ValueError, TypeError, OverflowError):
                    seconds = 60
            raise ProviderError("RATE_LIMITED", seconds)
        raise ProviderError("PROVIDER_TEMPORARY_ERROR")

    async def list_calendars(self, access_token):
        return await asyncio.to_thread(self._list, access_token)

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
                    if response.status_code != 400:  # Already revoked is idempotent.
                        self._check(response)
            except requests.RequestException:
                raise ProviderError("PROVIDER_TEMPORARY_ERROR") from None

        await asyncio.to_thread(revoke)
