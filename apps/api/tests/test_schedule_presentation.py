"""Shared presentation and Telegram clipboard boundary; no network."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from hub.calendar_events.domain import build_technician_schedule
from hub.calendar_events.normalization import normalize_event
from hub.google_calendar.legacy_presentation import END, START, present
from hub.schedule_delivery.domain import Payload, from_schedule
from hub.telegram.adapter import TelegramBotAdapter
from tests.test_calendar_events import DAY, ZONE, item

SEND = TelegramBotAdapter.send_schedule


def projection(raw):
    events = [normalize_event(row, ZONE) for row in raw]
    jobs, _ = build_technician_schedule(uuid4(), DAY, ZONE, events)
    return SimpleNamespace(
        operational_date=DAY,
        technician=SimpleNamespace(first_name="Alex", last_name="Test"),
        jobs=jobs,
    )


@pytest.mark.parametrize("phone", ["954-612-7891", "(954) 612-7891", "+1 954.612.7891"])
def test_google_legacy_adapter_display_only(phone):
    raw = item(
        title=f"1. FL Miami Duct {phone}",
        location="14800 Starfire Way, Tukwila, WA 98188",
        description=(
            "Customer: Michael Torres\nmichael@example.com\nCode: 4182\n2 main ducts + dryer vent\n"
            "confirmed by Karen\n09/29 > 10/06 9-11 Andrey\nlvm - Milad\n"
            "Call 15 minutes before arrival.\n"
            "*** Amount of closed project: $111 ***\n" + START + "secret report" + END
        ),
    )
    original = deepcopy(raw)
    value = present(projection([raw]).jobs[0])
    assert value.title == "FL Miami Duct" and value.phone == "954-612-7891"
    assert value.address == raw["location"]
    for useful in ["Michael Torres", "michael@example.com", "4182", "dryer vent", "Call 15"]:
        assert useful in value.details
    for hidden in ["Karen", "Andrey", "Milad", "$111", "secret report", START]:
        assert hidden not in value.details
    assert raw == original


@pytest.mark.parametrize("callback", [None, "sch:fake"])
async def test_eight_jobs_copy_exact_addresses_and_ack_only_private(callback):
    raw = [
        item(
            str(i),
            title=f"{i}. Duct",
            location=f"{i} Main St, Unit # 2",
            description="Customer: Fictional",
        )
        for i in range(1, 9)
    ]
    payload = from_schedule(projection(raw))
    message = payload.render(waiting_confirmation=callback is None)
    assert message.count("\u2501" * 20) == 7
    assert [address for _, address in payload.copy_addresses()] == [r["location"] for r in raw]
    assert (
        "Waiting for technician confirmation" in message
        if callback is None
        else "Waiting for technician confirmation" not in message
    )
    adapter = object.__new__(TelegramBotAdapter)
    adapter.bot = SimpleNamespace(
        send_message=AsyncMock(return_value=SimpleNamespace(message_id=1))
    )
    await SEND(
        adapter, -100 if callback is None else 100, message, callback, payload.copy_addresses()
    )
    keyboard = adapter.bot.send_message.call_args.kwargs["reply_markup"].inline_keyboard
    assert len(keyboard) == 8 + (callback is not None)
    assert [row[0].copy_text.text for row in keyboard[:8]] == [r["location"] for r in raw]
    assert all(row[0].callback_data is None for row in keyboard[:8])
    if callback:
        assert keyboard[-1][0].callback_data == callback


def test_old_version_snapshot_fingerprint_compatibility():
    import hashlib
    import json

    value = {
        "version": 1,
        "target_date": "2026-10-09",
        "technician_name": "Alex",
        "jobs": [{"time": "08:00", "title": "Legacy", "location": None}],
    }
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"))
    assert (
        Payload.model_validate(value).fingerprint == hashlib.sha256(canonical.encode()).hexdigest()
    )


def test_useful_notes_mentioning_report_or_payment_are_not_legacy_history():
    raw = item(description="Customer needs a work report copy.\nAsk about type of payment options.")
    assert present(projection([raw]).jobs[0]).details == raw["description"]
