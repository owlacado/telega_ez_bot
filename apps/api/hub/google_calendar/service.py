"""OAuth lifecycle and atomic full-scan reconciliation; network runs outside transactions."""

import json
import secrets
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select, text, update

from hub.audit.service import audit
from hub.auth.models import Manager, ManagerSession
from hub.auth.security import digest, now
from hub.calendars.models import Calendar, CalendarAssignment
from hub.core.secrets import SecretCipher
from hub.google_calendar.models import CalendarConnection, GoogleOAuthAttempt
from hub.google_calendar.schemas import GoogleConnectionRead
from hub.google_calendar.types import EVENT_SCOPE, SCOPE, SHEETS_SCOPE, ProviderError
from hub.telegram.locks import advisory_guard, lock_key


async def mutation_lock(db):
    await db.execute(
        text("SELECT pg_advisory_xact_lock(:key)"), {"key": lock_key("calendar-mutations", 0)}
    )


async def current(db):
    return await db.scalar(
        select(CalendarConnection).where(CalendarConnection.is_current.is_(True))
    )


def cipher(request):
    key = request.app.state.settings.google_calendar_credential_encryption_key
    if key is None:
        raise HTTPException(503, "CONFIGURATION_ERROR")
    return SecretCipher(key.get_secret_value())


def provider(request):
    value = request.app.state.google_provider
    if value is None:
        raise HTTPException(503, "CONFIGURATION_ERROR")
    return value


async def impact_details(db, connection):
    if connection is None:
        return None, 0, 0
    rows = (
        await db.execute(
            select(
                Calendar.id,
                Calendar.name,
                Calendar.excluded_at,
                CalendarAssignment.id,
                CalendarAssignment.technician_id,
            )
            .outerjoin(
                CalendarAssignment,
                (CalendarAssignment.calendar_id == Calendar.id)
                & CalendarAssignment.is_active.is_(True),
            )
            .where(Calendar.provider_connection_id == connection.id)
            .order_by(Calendar.id)
        )
    ).all()
    return (
        digest(json.dumps([[str(value) for value in row] for row in rows])),
        sum(row[2] is None for row in rows),
        sum(row[3] is not None for row in rows),
    )


async def impact_version(db, connection):
    return (await impact_details(db, connection))[0]


async def status(request, db):
    connection = await current(db)
    result = GoogleConnectionRead(
        enabled=request.app.state.settings.google_mode != "disabled",
        demo_enabled=request.app.state.settings.app_env in {"development", "test"},
    )
    if connection:
        for name in (
            "id",
            "generation",
            "status",
            "account_label",
            "last_success_at",
            "last_error_code",
            "retry_at",
            "granted_scopes",
        ):
            setattr(result, name, getattr(connection, name))
    result.impact_version, result.calendar_count, result.assignment_count = await impact_details(
        db, connection
    )
    return result


def expected(connection, identifier, generation):
    if (connection.id if connection else None) != identifier or (
        connection.generation if connection else None
    ) != generation:
        raise HTTPException(409, "Connection changed. Refresh and try again.")


async def start(request, db, payload):
    adapter = provider(request)
    secret_cipher = cipher(request)
    await mutation_lock(db)
    connection = await current(db)
    expected(connection, payload.expected_connection_id, payload.expected_generation)
    if (connection and payload.mode == "CONNECT") or (not connection and payload.mode != "CONNECT"):
        raise HTTPException(409, "Choose the current connection action.")
    if payload.mode == "SWITCH" and not payload.confirm_replace:
        raise HTTPException(
            409, "Confirm the calendar and assignment impact before replacing the account."
        )
    impact = await impact_version(db, connection) if payload.mode == "SWITCH" else None
    if payload.mode == "SWITCH" and payload.expected_impact_version != impact:
        raise HTTPException(409, "Calendar impact changed. Refresh and confirm again.")
    state = secrets.token_urlsafe(32)
    if (
        payload.request_event_access or payload.request_sheets_access
    ) and payload.mode != "RECONNECT":
        raise HTTPException(409, "Permission upgrades require a same-account reconnect.")
    event_access = payload.request_event_access or bool(
        connection and EVENT_SCOPE in connection.granted_scopes
    )
    sheets_access = payload.request_sheets_access or bool(
        connection and SHEETS_SCOPE in connection.granted_scopes
    )
    authorization = adapter.build_authorization_url(
        state, event_access=event_access, sheets_access=sheets_access
    )
    await db.execute(
        update(GoogleOAuthAttempt)
        .where(
            GoogleOAuthAttempt.session_id == request.state.session_id,
            GoogleOAuthAttempt.consumed_at.is_(None),
        )
        .values(consumed_at=now(), encrypted_verifier=None)
    )
    attempt = GoogleOAuthAttempt(
        state_hash=digest(state),
        manager_id=request.state.manager_id,
        session_id=request.state.session_id,
        encrypted_verifier=secret_cipher.encrypt(authorization.verifier),
        expires_at=now() + timedelta(minutes=10),
        expected_connection_id=connection.id if connection else None,
        expected_generation=connection.generation if connection else None,
        mode=payload.mode,
        request_event_access=event_access,
        request_sheets_access=sheets_access,
        expected_impact_version=impact,
    )
    db.add(attempt)
    await db.flush()
    audit(db, "google.connection.initiated", attempt.id, actor_id=request.state.manager_id)
    await db.commit()
    return authorization.url


async def unavailable(db, connection_id):
    await db.execute(
        update(Calendar)
        .where(Calendar.provider_connection_id == connection_id)
        .values(availability="UNAVAILABLE")
    )


async def reconcile(db, connection, calendars):
    # The provider must finish ALL pages before entering this transaction.
    rows = {
        row.provider_calendar_id: row
        for row in (
            await db.scalars(
                select(Calendar).where(Calendar.provider_connection_id == connection.id)
            )
        ).all()
    }
    seen = set()
    for item in calendars:
        if item.provider_id in seen:
            raise ProviderError("MALFORMED_RESPONSE")
        seen.add(item.provider_id)
        row = rows.get(item.provider_id)
        if row is None:
            row = Calendar(
                source="GOOGLE",
                provider_connection_id=connection.id,
                provider_calendar_id=item.provider_id,
            )
            db.add(row)
        row.name, row.timezone, row.primary, row.access_role = (
            item.name,
            item.timezone,
            item.primary,
            item.access_role,
        )
        row.availability, row.last_seen_at = "AVAILABLE", now()
        # excluded_at / excluded_by and assignment rows are deliberately untouched.
    for identifier, row in rows.items():
        if identifier not in seen:
            row.availability = "UNAVAILABLE"
    connection.last_success_at = now()
    connection.last_error_code = None
    connection.retry_at = None
    connection.status = "CONNECTED"
    await db.flush()


async def callback(request):
    pairs = request.state.google_callback
    parameters = dict(pairs)
    state = parameters.get("state", "")
    if len(state) != 43 or len(parameters) != len(pairs):
        return False
    factory = request.app.state.session_factory
    async with factory() as db:
        attempt = await db.scalar(
            select(GoogleOAuthAttempt)
            .where(GoogleOAuthAttempt.state_hash == digest(state))
            .with_for_update()
        )
        if (
            attempt is None
            or attempt.manager_id != request.state.manager_id
            or attempt.session_id != request.state.session_id
            or attempt.consumed_at is not None
            or attempt.expires_at <= now()
        ):
            return False
        encrypted_verifier = attempt.encrypted_verifier
        attempt.consumed_at, attempt.encrypted_verifier = now(), None
        await db.commit()  # State is burned before external I/O, including failed exchange.
    try:
        code = parameters.get("code", "")
        if parameters.get("error") or not code or len(code) > 4096:
            raise ProviderError("REAUTH_REQUIRED")
        adapter, secret_cipher = provider(request), cipher(request)
        # Serialize exchange/activation with disconnect/revoke. No SQL transaction held.
        async with advisory_guard(request.app.state.google_lock_engine, "google-lifecycle", 0):
            async with factory() as db:
                snapshot = await current(db)
                expected(snapshot, attempt.expected_connection_id, attempt.expected_generation)
                if attempt.expires_at <= now():
                    raise ProviderError("REAUTH_REQUIRED")
            grant = await adapter.exchange_authorization_code(
                code,
                secret_cipher.decrypt(encrypted_verifier),
                **({"event_access": True} if attempt.request_event_access else {}),
                **({"sheets_access": True} if attempt.request_sheets_access else {}),
            )
            if SCOPE not in grant.scopes:
                raise ProviderError("SCOPE_REQUIRED")
            calendars = await adapter.list_calendars(grant.access_token)
            identities = [item.provider_id for item in calendars if item.primary]
            if len(identities) != 1:
                raise ProviderError("ACCOUNT_IDENTITY_UNAVAILABLE")
            # Omitted refresh credentials may only reuse a decryptable, still-valid
            # grant for the same verified account. All verification is outside SQL.
            if not grant.refresh_token:
                if (
                    not snapshot
                    or snapshot.account_key != identities[0]
                    or not snapshot.encrypted_refresh_token
                ):
                    raise ProviderError("REAUTH_REQUIRED")
                old_token = secret_cipher.decrypt(snapshot.encrypted_refresh_token)
                verified = await adapter.refresh_credentials(
                    old_token,
                    **(
                        {"scopes": tuple(grant.scopes)}
                        if {EVENT_SCOPE, SHEETS_SCOPE}.intersection(grant.scopes)
                        else {}
                    ),
                )
                if SCOPE not in verified.scopes:
                    raise ProviderError("SCOPE_REQUIRED")
                old_calendars = await adapter.list_calendars(verified.access_token)
                if [c.provider_id for c in old_calendars if c.primary] != identities:
                    raise ProviderError("ACCOUNT_IDENTITY_UNAVAILABLE")
                # A retained refresh grant must carry the upgraded capability too.
                grant = replace(
                    grant,
                    refresh_token=verified.refresh_token or old_token,
                    scopes=tuple(s for s in grant.scopes if s in verified.scopes),
                )
            async with factory() as db:
                await mutation_lock(db)
                session = await db.scalar(
                    select(ManagerSession)
                    .join(Manager)
                    .where(
                        ManagerSession.id == request.state.session_id,
                        ManagerSession.revoked_at.is_(None),
                        ManagerSession.expires_at > now(),
                        Manager.is_active.is_(True),
                    )
                    .with_for_update()
                )
                if session is None:
                    raise ProviderError("REAUTH_REQUIRED")
                old = await current(db)
                expected(old, attempt.expected_connection_id, attempt.expected_generation)
                if attempt.mode == "SWITCH" and (
                    not attempt.expected_impact_version
                    or attempt.expected_impact_version != await impact_version(db, old)
                ):
                    raise ProviderError("REAUTH_REQUIRED")
                same = old is not None and old.account_key == identities[0]
                if old and not same and attempt.mode != "SWITCH":
                    raise ProviderError("REAUTH_REQUIRED")
                if not grant.refresh_token and not (same and old.encrypted_refresh_token):
                    raise ProviderError("REAUTH_REQUIRED")
                replaced_credential = old.encrypted_refresh_token if old and not same else None
                if old and not same:
                    old.is_current, old.status, old.encrypted_refresh_token = (
                        False,
                        "DISCONNECTED",
                        None,
                    )
                    old.generation += 1
                    await unavailable(db, old.id)
                    audit(
                        db, "google.connection.replaced", old.id, actor_id=request.state.manager_id
                    )
                    await db.flush()
                connection = (
                    old
                    if same
                    else await db.scalar(
                        select(CalendarConnection).where(
                            CalendarConnection.account_key == identities[0]
                        )
                    )
                )
                if connection is None:
                    connection = CalendarConnection(
                        account_key=identities[0], created_by_user_id=request.state.manager_id
                    )
                    db.add(connection)
                else:
                    connection.generation += 1
                connection.is_current, connection.status = True, "CONNECTED"
                connection.account_label = "Google Calendar account"
                connection.granted_scopes, connection.connected_at = list(grant.scopes), now()
                if grant.refresh_token:
                    connection.encrypted_refresh_token = secret_cipher.encrypt(grant.refresh_token)
                await db.flush()
                # Discovery at connect verifies identity; explicit Scan refreshes it later.
                await reconcile(db, connection, calendars)
                audit(
                    db,
                    "google.connection.completed",
                    connection.id,
                    actor_id=request.state.manager_id,
                )
                await db.commit()
            if replaced_credential:
                try:
                    await adapter.revoke_credentials(secret_cipher.decrypt(replaced_credential))
                except Exception:
                    async with factory() as db:
                        audit(
                            db,
                            "google.revocation.failed",
                            old.id,
                            actor_id=request.state.manager_id,
                            outcome="FAILED",
                        )
                        await db.commit()
        return True
    except Exception:
        # Neither provider exceptions nor OAuth query strings are serialized/logged.
        async with factory() as db:
            audit(
                db,
                "google.connection.failed",
                attempt.id,
                actor_id=request.state.manager_id,
                outcome="FAILED",
            )
            await db.commit()
        return False


async def scan(request):
    adapter, secret_cipher = provider(request), cipher(request)
    factory = request.app.state.session_factory
    try:
        async with advisory_guard(
            request.app.state.google_lock_engine, "google-scan", 0, wait=False
        ):
            async with factory() as db:
                connection = await current(db)
                if not connection or connection.status not in {"CONNECTED", "ERROR"}:
                    raise HTTPException(409, "Reconnect Google Calendar before scanning.")
                if connection.retry_at and connection.retry_at > now():
                    raise HTTPException(
                        429, "RATE_LIMITED: try again after the connection retry time."
                    )
                identifier, generation, encrypted = (
                    connection.id,
                    connection.generation,
                    connection.encrypted_refresh_token,
                )
            grant = None
            try:
                async with advisory_guard(
                    request.app.state.google_lock_engine, "google-lifecycle", 0
                ):
                    async with factory() as db:
                        latest = await current(db)
                        expected(latest, identifier, generation)
                        encrypted = latest.encrypted_refresh_token
                    token = secret_cipher.decrypt(encrypted)
                    grant = await adapter.refresh_credentials(
                        token,
                        **(
                            {"scopes": tuple(latest.granted_scopes)}
                            if {EVENT_SCOPE, SHEETS_SCOPE}.intersection(latest.granted_scopes)
                            else {}
                        ),
                    )
                    if SCOPE not in grant.scopes:
                        raise ProviderError("SCOPE_REQUIRED")
                    # Persist a rotated credential before pagination, which can fail.
                    # Recheck generation so an old scan cannot resurrect disconnected grants.
                    if (grant.refresh_token and grant.refresh_token != token) or set(
                        grant.scopes
                    ) != set(latest.granted_scopes):
                        async with factory() as db:
                            await mutation_lock(db)
                            connection = await current(db)
                            expected(connection, identifier, generation)
                            if grant.refresh_token:
                                connection.encrypted_refresh_token = secret_cipher.encrypt(
                                    grant.refresh_token
                                )
                            connection.granted_scopes = list(grant.scopes)
                            await db.commit()
                calendars = await adapter.list_calendars(grant.access_token)
            except HTTPException:
                raise
            except Exception as exc:
                code = (
                    exc.code
                    if isinstance(exc, ProviderError)
                    else "REAUTH_REQUIRED"
                    if isinstance(exc, ValueError)
                    else "PROVIDER_TEMPORARY_ERROR"
                )
                retry = exc.retry_after if isinstance(exc, ProviderError) else 60
                async with factory() as db:
                    await mutation_lock(db)
                    connection = await current(db)
                    expected(connection, identifier, generation)
                    permanent = code in {"REAUTH_REQUIRED", "SCOPE_REQUIRED"}
                    connection.status = "REAUTH_REQUIRED" if permanent else "ERROR"
                    connection.last_error_code = code
                    if permanent:
                        connection.retry_at = None
                    else:
                        try:
                            connection.retry_at = now() + timedelta(seconds=retry)
                        except OverflowError:
                            connection.retry_at = datetime(9999, 12, 30, tzinfo=UTC)
                    if permanent:
                        await unavailable(db, identifier)
                    audit(
                        db,
                        "google.scan.failed",
                        identifier,
                        actor_id=request.state.manager_id,
                        outcome="FAILED",
                    )
                    await db.commit()
                raise HTTPException(429 if code == "RATE_LIMITED" else 503, code) from None
            async with factory() as db:
                await mutation_lock(db)
                connection = await current(db)
                expected(connection, identifier, generation)
                await reconcile(db, connection, calendars)
                audit(db, "google.scan.completed", identifier, actor_id=request.state.manager_id)
                await db.commit()
            return len(calendars)
    except RuntimeError as exc:
        if str(exc) == "POLLER_ALREADY_RUNNING":
            raise HTTPException(409, "A calendar scan is already running.") from None
        raise


async def disconnect(request, payload):
    factory = request.app.state.session_factory
    async with advisory_guard(request.app.state.google_lock_engine, "google-lifecycle", 0):
        async with factory() as db:
            await mutation_lock(db)
            connection = await current(db)
            expected(connection, payload.expected_connection_id, payload.expected_generation)
            encrypted = connection.encrypted_refresh_token
            connection.encrypted_refresh_token, connection.status = None, "DISCONNECTED"
            connection.generation += 1
            connection.last_error_code, connection.retry_at = None, None
            await unavailable(db, connection.id)
            audit(
                db,
                "google.connection.disconnected",
                connection.id,
                actor_id=request.state.manager_id,
            )
            await db.commit()
        if encrypted:
            try:
                await provider(request).revoke_credentials(cipher(request).decrypt(encrypted))
            except Exception:
                async with factory() as db:
                    audit(
                        db,
                        "google.revocation.failed",
                        connection.id,
                        actor_id=request.state.manager_id,
                        outcome="FAILED",
                    )
                    await db.commit()
