from urllib.parse import parse_qs, urlparse

from sqlalchemy.ext.asyncio import async_sessionmaker

from hub.telegram.transport import parse_update
from hub.telegram.updates import process_update
from tests.fakes import BOT_ID, BOT_USERNAME


async def technician(client, name="Demo"):
    response = await client.post("/api/technicians", json={"first_name": name, "last_name": "Test"})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def state(client, identifier):
    response = await client.get(f"/api/technicians/{identifier}/telegram")
    assert response.status_code == 200, response.text
    return response.json()


async def issue(client, identifier, purpose="PRIVATE_ACCOUNT", replace=False):
    current = (await state(client, identifier))[
        "private" if purpose == "PRIVATE_ACCOUNT" else "group"
    ]
    response = await client.post(
        f"/api/technicians/{identifier}/telegram/invitations",
        json={
            "purpose": purpose,
            "replace": replace,
            "expected_generation": current["generation"],
            "confirmation": "REPLACE" if replace else "CONNECT",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def event(invitation, update_id=1, user_id=12345678, chat_type="private", chat_id=None, **extra):
    payload = next(iter(parse_qs(urlparse(invitation["link"]).query).values()))[0]
    command = "/start" if chat_type == "private" else f"/start@{BOT_USERNAME}"
    raw = {
        "update_id": update_id,
        "message": {
            "chat": {
                "id": chat_id if chat_id is not None else user_id,
                "type": chat_type,
                "title": "DEMO Test Group",
            },
            "from": {"id": user_id, "is_bot": False, "first_name": "Demo Candidate"},
            "text": f"{command} {payload}",
            **extra,
        },
    }
    return parse_update(raw, BOT_USERNAME)


async def claim(engine, provider, invitation, **kwargs):
    return await process_update(
        async_sessionmaker(engine, expire_on_commit=False),
        provider,
        event(invitation, **kwargs),
        BOT_ID,
    )


async def review(client, identifier, invitation, decision="APPROVE"):
    return await client.post(
        f"/api/technicians/{identifier}/telegram/invitations/{invitation['invitation']['id']}/review",
        json={"decision": decision},
    )


async def connected_private(client, engine, provider, *, user_id=12345678, update_id=1):
    identifier = await technician(client)
    invitation = await issue(client, identifier)
    assert (
        await claim(engine, provider, invitation, user_id=user_id, update_id=update_id)
    ).outcome == "AWAITING_APPROVAL"
    assert (await review(client, identifier, invitation)).status_code == 204
    return identifier


async def connected_group(
    client, engine, provider, *, user_id=12345678, chat_id=-1009876543210, update_id=1
):
    identifier = await connected_private(
        client, engine, provider, user_id=user_id, update_id=update_id
    )
    invitation = await issue(client, identifier, "WORK_GROUP")
    provider.group(chat_id, user_id, user_id)
    result = await claim(
        engine,
        provider,
        invitation,
        user_id=user_id,
        chat_type="supergroup",
        chat_id=chat_id,
        update_id=update_id + 1,
    )
    assert result.outcome == "AWAITING_APPROVAL"
    assert (await review(client, identifier, invitation)).status_code == 204
    return identifier
