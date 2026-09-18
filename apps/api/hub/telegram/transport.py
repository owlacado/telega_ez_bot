"""Translate trusted Bot API updates into minimal application events. No DB access."""

import re

from hub.telegram.types import TrustedEvent


def identifier(value: object) -> int | None:
    return (
        value
        if isinstance(value, int) and not isinstance(value, bool) and -(2**63) < value < 2**63
        else None
    )


def parse_update(update: object, bot_username: str) -> TrustedEvent:
    if not isinstance(update, dict):
        raise ValueError("MALFORMED_UPDATE_ID")
    update_id = identifier(update.get("update_id"))
    if update_id is None or update_id < 0:
        raise ValueError("MALFORMED_UPDATE_ID")
    try:
        return _parse_update(update, bot_username)
    except (AttributeError, TypeError, ValueError):
        return TrustedEvent(update_id, "IGNORED")


def _parse_update(update: dict, bot_username: str) -> TrustedEvent:
    update_id = identifier(update.get("update_id"))
    if update_id is None:
        raise ValueError("MALFORMED_UPDATE_ID")
    callback = update.get("callback_query")
    if callback:
        query_id = callback.get("id")
        payload = callback.get("data")
        user, message = callback.get("from", {}), callback.get("message", {})
        chat = message.get("chat", {})
        if not isinstance(query_id, str) or not 1 <= len(query_id) <= 256:
            return TrustedEvent(update_id, "IGNORED")
        return TrustedEvent(
            update_id,
            "CALLBACK",
            callback_query_id=query_id,
            payload=payload
            if isinstance(payload, str) and re.fullmatch(r"sch:[A-Za-z0-9_-]{43}", payload)
            else None,
            chat_id=identifier(chat.get("id")),
            chat_type=chat.get("type"),
            user_id=identifier(user.get("id")),
            user_is_bot=user.get("is_bot") is not False,
            anonymous=not identifier(user.get("id")),
            message_id=identifier(message.get("message_id")),
        )
    membership = update.get("my_chat_member") or update.get("chat_member")
    if membership:
        chat = membership.get("chat", {})
        member = membership.get("new_chat_member", {})
        user = member.get("user", {})
        return TrustedEvent(
            update_id,
            "BOT_MEMBERSHIP" if "my_chat_member" in update else "MEMBER",
            chat_id=identifier(chat.get("id")),
            chat_type=chat.get("type"),
            member_user_id=identifier(user.get("id")),
            member_status=member.get("status"),
            member_present=member.get("status") in {"creator", "administrator", "member"}
            or (member.get("status") == "restricted" and member.get("is_member") is True),
        )
    message = update.get("message")
    if not message:
        return TrustedEvent(update_id, "IGNORED")
    chat, user = message.get("chat", {}), message.get("from", {})
    chat_id, user_id = identifier(chat.get("id")), identifier(user.get("id"))
    if message.get("migrate_to_chat_id") is not None and chat.get("type") == "group":
        return TrustedEvent(
            update_id,
            "MIGRATION",
            chat_id=chat_id,
            migrated_chat_id=identifier(message.get("migrate_to_chat_id")),
        )
    if message.get("migrate_from_chat_id") is not None and chat.get("type") == "supergroup":
        return TrustedEvent(
            update_id,
            "MIGRATION",
            chat_id=identifier(message.get("migrate_from_chat_id")),
            migrated_chat_id=chat_id,
        )
    raw = message.get("text", "")
    if not isinstance(raw, str) or len(raw) > 4096 or message.get("forward_origin"):
        return TrustedEvent(update_id, "IGNORED")
    words = raw.strip().split(maxsplit=1)
    command, payload = None, None
    if words:
        name, _, addressed = words[0].partition("@")
        if not addressed or addressed.lower() == bot_username.lower():
            command = (
                name.lower()
                if name.lower() in {"/start", "/help", "/status", "/getid", "/report"}
                else None
            )
        if raw.strip().lower() == "get id":
            command = "/getid"
        if raw.strip().lower() == "submit report":
            command = "/report"
        if len(words) == 2 and re.fullmatch(r"[A-Za-z0-9_-]{43}", words[1]):
            payload = words[1]
        elif len(words) == 2:
            payload = "INVALID"  # Do not retain raw registration messages.
    return TrustedEvent(
        update_id,
        "COMMAND",
        chat_id=chat_id,
        chat_type=chat.get("type"),
        user_id=user_id,
        user_is_bot=user.get("is_bot") is not False,
        anonymous=message.get("sender_chat") is not None or user_id is None,
        display_name=" ".join(filter(None, [user.get("first_name"), user.get("last_name")]))[:200]
        or None,
        username=(user.get("username") or "")[:64] or None,
        chat_title=(chat.get("title") or "")[:200] or None,
        command=command,
        payload=payload,
    )
