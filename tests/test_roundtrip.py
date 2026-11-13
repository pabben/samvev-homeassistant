"""Opt-in interoperability tests against real Samvev code and a synthetic DB.

Start tests/ha-bridge/server.mts from the companion backend checkout first. No
Samvev transport or Home Assistant platform is mocked in these tests.
"""

import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import aiohttp
import pytest
from homeassistant.components.calendar.const import (
    DATA_COMPONENT,
    CalendarEntityFeature,
)
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samvev.const import CONF_API_TOKEN, CONF_BASE_URL, DOMAIN

REAL_URL = os.environ.get("SAMVEV_REAL_URL", "")
pytestmark = [
    pytest.mark.skipif(
        not REAL_URL, reason="Requires the isolated actual Samvev server"
    ),
    pytest.mark.enable_socket,
]
CAPABILITIES = [
    f"ha.{content}.{access}"
    for content in ("groceries", "messages", "calendar")
    for access in ("read", "write")
]


@pytest.fixture
async def real_connection(hass, socket_enabled):
    """Provision a synthetic household connection through real manager APIs."""
    if REAL_URL != "http://127.0.0.1:4193":
        pytest.fail(
            "Roundtrip tests refuse any URL except the isolated localhost fixture"
        )
    async with aiohttp.ClientSession(
        cookie_jar=aiohttp.CookieJar(unsafe=True)
    ) as admin:
        csrf = ""

        async def request(method, path, payload=None, expected=200):
            headers = {"Origin": REAL_URL}
            if csrf:
                headers["x-csrf-token"] = csrf
            async with admin.request(
                method,
                REAL_URL + "/api/v1" + path,
                headers=headers,
                json=payload,
                allow_redirects=False,
            ) as response:
                assert response.status == expected
                return await response.json() if response.status != 204 else {}

        login = await request(
            "POST",
            "/auth/login",
            {
                "email": "ha-owner@example.invalid",
                "password": "Synthetic-HA-roundtrip-password-42",
            },
        )
        csrf = login["csrfToken"]
        me = await request("GET", "/me")
        household_id = me["memberships"][0]["household_id"]
        base = f"/households/{household_id}"
        created = await request(
            "POST",
            base + "/integrations",
            {
                "name": "Samvev HA",
                "displayIds": [],
                "credential": {
                    "name": "Synthetic HA",
                    "capabilities": CAPABILITIES,
                    "expiresAt": None,
                },
            },
            expected=201,
        )
        connection_id = created["connection"]["id"]
        sharing_path = f"{base}/integrations/{connection_id}/ha-sharing"
        sharing = await request(
            "PATCH",
            sharing_path,
            {
                "expectedRevision": 0,
                "listIds": ["groceries"],
                "household": True,
                "personIds": [],
                "calendarSourceIds": [],
            },
        )
        entry = MockConfigEntry(
            domain=DOMAIN,
            title="Samvev HA",
            data={CONF_BASE_URL: REAL_URL, CONF_API_TOKEN: created["credentialToken"]},
        )
        entry.add_to_hass(hass)
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done(wait_background_tasks=True)
        yield entry, request, base, sharing_path, sharing
        if entry.runtime_data:
            await hass.config_entries.async_unload(entry.entry_id)
        await request("POST", "/auth/logout", {}, expected=204)


async def test_actual_shopping_messages_calendar_and_revocation(hass, real_connection):  # noqa: PLR0915
    """Perform all three roundtrips through actual HA entities and actual Samvev."""
    entry, request, base, sharing_path, sharing = real_connection
    coordinator = entry.runtime_data.coordinator
    todo_id = "todo.samvev_ha_groceries"
    calendar_id = "calendar.samvev_ha_samvev"
    messages_id = "sensor.samvev_ha_messages"
    assert hass.states.get(todo_id) is not None
    assert hass.states.get(calendar_id) is not None

    # Existing Samvev content -> HA -> standard checkbox -> authoritative Samvev.
    added = await request(
        "POST",
        base + "/groceries",
        {
            "label": "Synthetic apples",
            "checked": False,
            "requestKey": str(uuid4()),
        },
        expected=201,
    )
    item_id = added["item"]["id"]
    await coordinator.async_refresh()
    await hass.services.async_call(
        "todo",
        "update_item",
        {
            "entity_id": todo_id,
            "item": item_id,
            "status": "completed",
        },
        blocking=True,
    )
    groceries = (await request("GET", base + "/groceries"))["items"]
    assert next(row for row in groceries if row["id"] == item_id)["checked"] is True
    await hass.services.async_call(
        "todo",
        "update_item",
        {
            "entity_id": todo_id,
            "item": item_id,
            "status": "needs_action",
            "rename": "Synthetic red apples",
        },
        blocking=True,
    )
    groceries = (await request("GET", base + "/groceries"))["items"]
    current = next(row for row in groceries if row["id"] == item_id)
    assert current["label"] == "Synthetic red apples"
    assert current["checked"] is False
    # A competing Samvev edit wins; HA must not silently adopt its newer revision.
    await request(
        "PATCH",
        f"{base}/groceries/{item_id}",
        {
            "label": "Synthetic server winner",
            "expectedRevision": current["revision"],
            "requestKey": str(uuid4()),
        },
    )
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "todo",
            "update_item",
            {
                "entity_id": todo_id,
                "item": item_id,
                "rename": "Stale losing edit",
            },
            blocking=True,
        )
    assert (
        next(
            row for row in coordinator.data["lists"][0]["items"] if row["id"] == item_id
        )["label"]
        == "Synthetic server winner"
    )
    # Repeated create presses collapse to one authoritative server item.
    for _ in range(2):
        await hass.services.async_call(
            "todo",
            "add_item",
            {
                "entity_id": todo_id,
                "item": "Synthetic repeated milk",
            },
            blocking=True,
        )
    groceries = (await request("GET", base + "/groceries"))["items"]
    assert sum(row["label"] == "Synthetic repeated milk" for row in groceries) == 1
    await hass.services.async_call(
        "todo",
        "remove_item",
        {
            "entity_id": todo_id,
            "item": item_id,
        },
        blocking=True,
    )
    assert all(
        row["id"] != item_id
        for row in (await request("GET", base + "/groceries"))["items"]
    )

    # Multiple active messages; both authorship paths and lifecycle changes.
    now = datetime.now(UTC)
    expiry = (now + timedelta(hours=2)).isoformat()
    browser_message = await request(
        "POST",
        base + "/messages",
        {
            "body": "Synthetic member notice",
            "importance": "normal",
            "audience": {"household": True, "personIds": [], "displayIds": []},
            "expiresAt": expiry,
            "idempotencyKey": str(uuid4()),
        },
        expected=201,
    )
    await coordinator.async_refresh()
    created = await hass.services.async_call(
        DOMAIN,
        "create_message",
        {
            "body": "Synthetic HA notice",
            "importance": "attention",
            "audience": {"household": True, "person_ids": []},
            "expires_at": expiry,
            "request_key": "actual-ha-message-roundtrip",
        },
        blocking=True,
        return_response=True,
    )
    message_id = created["message"]["id"]
    state = hass.states.get(messages_id)
    assert int(state.state) >= 2
    rows = state.attributes["messages"]
    assert (
        next(row for row in rows if row["id"] == message_id)["authorType"]
        == "integration"
    )
    assert any(row["id"] == browser_message["id"] for row in rows)
    await hass.services.async_call(
        DOMAIN,
        "update_message",
        {
            "message_id": message_id,
            "body": "Synthetic updated HA notice",
        },
        blocking=True,
    )
    member_rows = (await request("GET", base + "/messages"))["messages"]
    assert (
        next(row for row in member_rows if row["id"] == message_id)["body"]
        == "Synthetic updated HA notice"
    )
    await hass.services.async_call(
        DOMAIN,
        "withdraw_message",
        {
            "message_id": message_id,
        },
        blocking=True,
    )
    assert all(row["id"] != message_id for row in coordinator.data["messages"])
    await request(
        "PATCH",
        f"{base}/messages/{browser_message['id']}",
        {
            "body": "Synthetic updated member notice",
            "expectedRevision": 1,
        },
    )
    await coordinator.async_refresh()
    assert any(
        row["body"] == "Synthetic updated member notice"
        for row in coordinator.data["messages"]
    )
    await request(
        "POST",
        f"{base}/messages/{browser_message['id']}/withdraw",
        {"expectedRevision": 2},
    )
    await coordinator.async_refresh()
    assert all(
        row["id"] != browser_message["id"] for row in coordinator.data["messages"]
    )

    # HA native event -> actual Samvev home -> interval query -> edit/cancel.
    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "entity_id": calendar_id,
            "summary": "Synthetic DST appointment",
            "start_date_time": datetime(
                2027, 3, 28, 1, 30, tzinfo=ZoneInfo("Europe/Oslo")
            ),
            "end_date_time": datetime(
                2027, 3, 28, 3, 30, tzinfo=ZoneInfo("Europe/Oslo")
            ),
            "location": "Synthetic room",
        },
        blocking=True,
    )
    calendar = hass.data[DATA_COMPONENT].get_entity(calendar_id)
    start = datetime(2027, 3, 27, tzinfo=UTC)
    end = datetime(2027, 3, 30, tzinfo=UTC)
    events = await calendar.async_get_events(hass, start, end)
    event = next(row for row in events if row.summary == "Synthetic DST appointment")
    assert event.end.astimezone(UTC) - event.start.astimezone(UTC) == timedelta(hours=1)
    # Use a current event too so the existing Home projection includes it.
    tomorrow = (now + timedelta(days=1)).date()
    await hass.services.async_call(
        "calendar",
        "create_event",
        {
            "entity_id": calendar_id,
            "summary": "Synthetic all-day appointment",
            "start_date": tomorrow.isoformat(),
            "end_date": (tomorrow + timedelta(days=1)).isoformat(),
        },
        blocking=True,
    )
    current_events = await calendar.async_get_events(hass, now, now + timedelta(days=3))
    all_day = next(
        row for row in current_events if row.summary == "Synthetic all-day appointment"
    )
    assert all_day.all_day
    assert all_day.start == tomorrow
    home = await request("GET", base + "/home")
    assert "Synthetic all-day appointment" in str(home)
    await calendar.async_update_event(
        event.uid,
        {
            "summary": "Synthetic moved appointment",
            "dtstart": datetime(2027, 3, 28, 5, tzinfo=UTC),
            "dtend": datetime(2027, 3, 28, 6, tzinfo=UTC),
        },
    )
    moved = await calendar.async_get_events(hass, start, end)
    assert (
        next(row for row in moved if row.uid == event.uid).summary
        == "Synthetic moved appointment"
    )
    await calendar.async_delete_event(event.uid)
    assert all(
        row.uid != event.uid
        for row in await calendar.async_get_events(hass, start, end)
    )

    # Reload retains identity and server content, then narrowed grants erase data.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done(wait_background_tasks=True)
    coordinator = entry.runtime_data.coordinator
    assert any(
        row["label"] == "Synthetic repeated milk"
        for row in coordinator.data["lists"][0]["items"]
    )
    await request(
        "PATCH",
        sharing_path,
        {
            "expectedRevision": sharing["revision"],
            "listIds": [],
            "household": False,
            "personIds": [],
            "calendarSourceIds": [],
        },
    )
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert coordinator.data["lists"] == []
    assert hass.states.get(todo_id).state == "unavailable"
    assert hass.states.get(messages_id).attributes.get("messages", []) == []
    assert "Synthetic all-day appointment" not in str(
        hass.states.get(calendar_id).attributes
    )
    # Fully revoke the stable connection: no protected attributes survive reauth.
    connection_id = coordinator.connection["connectionId"]
    connections = (await request("GET", base + "/integrations"))["connections"]
    connection = next(row for row in connections if row["id"] == connection_id)
    await request(
        "POST",
        f"{base}/integrations/{connection_id}/revoke",
        {"expectedRevision": connection["revision"]},
    )
    await coordinator.async_refresh()
    assert coordinator.data == {}
    assert coordinator.authorization_revoked
    assert hass.states.get("sensor.samvev_ha_connection_status").state == "disconnected"
    assert hass.states.get(messages_id).attributes.get("messages", []) == []


async def test_provisioning_command_actual_server(
    tmp_path, monkeypatch, socket_enabled
):
    """The documented operator command creates only selected grants and a 0600 file."""
    from types import SimpleNamespace  # noqa: PLC0415

    from scripts.provision_connection import ManagerSession, provision  # noqa: PLC0415

    output = tmp_path / "synthetic-credential.json"
    args = SimpleNamespace(
        url=REAL_URL,
        email="ha-owner@example.invalid",
        household=None,
        name="Synthetic provisioned HA",
        inspect=False,
        share_groceries=True,
        write_groceries=True,
        messages=False,
        write_messages=False,
        calendar=False,
        write_calendar=False,
        share_household=False,
        person=[],
        calendar_source=[],
        output=output,
    )
    monkeypatch.setattr(
        "scripts.provision_connection.getpass.getpass",
        lambda _: "Synthetic-HA-roundtrip-password-42",
    )

    def run():
        session = ManagerSession(REAL_URL)
        try:
            provision(args, session)
        finally:
            session.close()

    await asyncio.to_thread(run)
    assert output.stat().st_mode & 0o777 == 0o600
    import json  # noqa: PLC0415

    saved = json.loads(output.read_text())
    async with (
        aiohttp.ClientSession() as session,
        session.get(
            REAL_URL + "/api/v1/ha/connection",
            headers={"Authorization": "Bearer " + saved["api_token"]},
        ) as response,
    ):
        assert response.status == 200
        connection = await response.json()
        assert connection["grants"]["listIds"] == ["groceries"]
        assert connection["grants"]["household"] is False
        assert connection["capabilities"] == [
            "ha.groceries.read",
            "ha.groceries.write",
        ]


async def test_actual_imported_calendar_is_complete_and_read_only(
    hass, real_connection
):
    """Actual backend source grants yield standard, read-only HA calendars."""
    entry, request, base, sharing_path, sharing = real_connection
    connections = (await request("GET", base + "/calendar-connections"))["connections"]
    source = next(
        source
        for connection in connections
        for source in connection["sources"]
        if source["name"] == "Synthetic imported series"
    )
    await request(
        "PATCH",
        sharing_path,
        {
            "expectedRevision": sharing["revision"],
            "listIds": ["groceries"],
            "household": True,
            "personIds": [],
            "calendarSourceIds": [source["id"]],
        },
    )
    coordinator = entry.runtime_data.coordinator
    await coordinator.async_refresh()
    await hass.async_block_till_done(wait_background_tasks=True)
    calendar = next(
        entity
        for state in hass.states.async_all("calendar")
        if (entity := hass.data[DATA_COMPONENT].get_entity(state.entity_id)).calendar_id
        == source["id"]
    )
    assert calendar.supported_features == CalendarEntityFeature(0)
    start = datetime.now(UTC)
    events = await calendar.async_get_events(hass, start, start + timedelta(days=3))
    assert len(events) == 3
    assert len({event.uid for event in events}) == 3
    assert all(
        event.summary.startswith("Synthetic imported occurrence") for event in events
    )
    with pytest.raises(HomeAssistantError):
        await calendar.async_create_event(
            summary="Forbidden imported write",
            dtstart=start,
            dtend=start + timedelta(hours=1),
        )
    with pytest.raises(HomeAssistantError):
        await calendar.async_update_event(events[0].uid, {"summary": "Forbidden edit"})
    with pytest.raises(HomeAssistantError):
        await calendar.async_delete_event(events[0].uid)
    again = await calendar.async_get_events(hass, start, start + timedelta(days=3))
    assert [event.uid for event in again] == [event.uid for event in events]
