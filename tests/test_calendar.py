"""Standard HA calendars keep full windows and Samvev's source restrictions."""

from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from homeassistant.components.calendar.const import (
    DATA_COMPONENT,
    CalendarEntityFeature,
)
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util

from custom_components.samvev.api import SamvevConnectionError
from custom_components.samvev.calendar import SamvevCalendar, _event

from .test_services import BASE_URL, setup_entry


def event_row(**changes) -> dict:
    """Build a synthetic native event with an observed revision."""
    return {
        "id": "event-one",
        "summary": "Synthetic appointment",
        "start": "2026-10-25T01:30:00+02:00",
        "end": "2026-10-25T02:30:00+01:00",
        "description": "",
        "location": "Test venue",
        "revision": 3,
        "readOnly": False,
        "source": "samvev",
        **changes,
    }


async def make_calendar(hass, aioclient_mock):
    """Create a real entity bound to the integration's live coordinator."""
    entry = await setup_entry(hass, aioclient_mock)
    entity = hass.data[DATA_COMPONENT].get_entity("calendar.samvev_ha_samvev")
    return entry, entity


async def test_full_window_all_day_overlap_dst_and_cancellation(
    hass, aioclient_mock, monkeypatch
) -> None:
    """Return every overlapping occurrence and preserve civil all-day dates."""
    entry, entity = await make_calendar(hass, aioclient_mock)
    rows = [
        event_row(),
        event_row(id="event-two", summary="Concurrent", readOnly=True, source="google"),
        event_row(id="all-day", start="2026-10-25", end="2026-10-27"),
    ]
    events_mock = AsyncMock(
        return_value={"events": rows, "serverNow": dt_util.utcnow().isoformat()}
    )
    monkeypatch.setattr(type(entry.runtime_data.client), "async_events", events_mock)
    start = datetime(2026, 10, 25, tzinfo=ZoneInfo("Europe/Oslo"))
    end = start + timedelta(days=2)
    events = await entity.async_get_events(hass, start, end)
    assert len(events) == 3
    all_day = next(event for event in events if event.uid == "all-day")
    assert all_day.all_day
    assert all_day.start == date(2026, 10, 25)
    timed = next(event for event in events if event.uid == "event-one")
    assert timed.end.astimezone(ZoneInfo("UTC")) - timed.start.astimezone(
        ZoneInfo("UTC")
    ) == timedelta(hours=2)
    events_mock.assert_awaited_once_with("samvev", start, end)
    events_mock.return_value["events"] = []
    assert await entity.async_get_events(hass, start, end) == []


async def test_own_create_update_delete_and_readonly_source(
    hass, aioclient_mock, monkeypatch
) -> None:
    """Own appointments support writes; imported appointments remain read-only."""
    entry, entity = await make_calendar(hass, aioclient_mock)
    assert entity.supported_features == (
        CalendarEntityFeature.CREATE_EVENT
        | CalendarEntityFeature.UPDATE_EVENT
        | CalendarEntityFeature.DELETE_EVENT
    )
    aioclient_mock.post(
        f"{BASE_URL}/api/v1/ha/calendars/samvev/events",
        status=201,
        json={"event": event_row()},
    )
    await entity.async_create_event(
        summary="All day", dtstart=date(2026, 10, 25), dtend=date(2026, 10, 26)
    )
    call = next(call for call in aioclient_mock.mock_calls if call[0].upper() == "POST")
    assert call[2]["start"] == "2026-10-25"
    assert call[2]["end"] == "2026-10-26"
    entity._events["event-one"] = event_row()  # noqa: SLF001
    aioclient_mock.patch(
        f"{BASE_URL}/api/v1/ha/calendars/samvev/events/event-one",
        json={"event": event_row(revision=4)},
    )
    await entity.async_update_event("event-one", {"summary": "Moved"})
    call = next(
        call for call in aioclient_mock.mock_calls if call[0].upper() == "PATCH"
    )
    assert call[2]["expectedRevision"] == 3
    aioclient_mock.delete(
        f"{BASE_URL}/api/v1/ha/calendars/samvev/events/event-one",
        json={"event": {"id": "event-one", "revision": 4}},
    )
    await entity.async_delete_event("event-one")
    entity._events["imported"] = event_row(id="imported", readOnly=True)  # noqa: SLF001
    with pytest.raises(HomeAssistantError):
        await entity.async_update_event("imported", {"summary": "Forbidden"})
    with pytest.raises(HomeAssistantError):
        await entity.async_update_event("unseen", {"summary": "Blind write"})
    with pytest.raises(HomeAssistantError):
        await entity.async_create_event(
            summary="Unsupported series", rrule="FREQ=WEEKLY"
        )
    entry.runtime_data.coordinator.data["calendars"].append(
        {"id": "source-one", "name": "Imported", "writable": False}
    )
    imported = SamvevCalendar(
        entry,
        entry.runtime_data.coordinator,
        {"id": "source-one", "name": "Imported", "writable": False},
    )
    assert imported.supported_features == 0
    with pytest.raises(HomeAssistantError):
        await imported.async_delete_event("event-one")


async def test_calendar_network_error_preserves_current_and_auth_clears(
    hass, aioclient_mock, monkeypatch
) -> None:
    """A failed interval read is unavailable, never an empty successful calendar."""
    entry, entity = await make_calendar(hass, aioclient_mock)

    row = event_row(
        start=(dt_util.utcnow() + timedelta(hours=1)).isoformat(),
        end=(dt_util.utcnow() + timedelta(hours=2)).isoformat(),
    )
    entity._current_events = [_event(row)]  # noqa: SLF001
    events_mock = AsyncMock(side_effect=SamvevConnectionError("Offline"))
    monkeypatch.setattr(type(entry.runtime_data.client), "async_events", events_mock)
    with pytest.raises(HomeAssistantError):
        await entity.async_update()
    assert entity.event is not None
    assert not entity.available
    entry.runtime_data.coordinator.data = {}
    entity._handle_coordinator_update()  # noqa: SLF001
    assert entity.event is None
    assert entity._events == {}  # noqa: SLF001


async def test_calendar_conflict_never_refetches_before_write(
    hass, aioclient_mock, monkeypatch
) -> None:
    """Preserve the observed revision rather than overwriting a concurrent edit."""
    _, entity = await make_calendar(hass, aioclient_mock)
    entity._events["event-one"] = event_row()  # noqa: SLF001
    aioclient_mock.patch(
        f"{BASE_URL}/api/v1/ha/calendars/samvev/events/event-one", status=409
    )
    with pytest.raises(HomeAssistantError):
        await entity.async_update_event("event-one", {"summary": "My change"})
    calls = [call for call in aioclient_mock.mock_calls if call[0].upper() == "PATCH"]
    assert len(calls) == 1
    assert calls[0][2]["expectedRevision"] == 3


async def test_two_day_agenda_household_midnight_dst_overlap_and_revocation(
    hass, aioclient_mock, monkeypatch, freezer
) -> None:
    """Show exact civil today/tomorrow, including earlier and spanning events."""
    freezer.move_to("2027-03-27T23:30:00Z")  # Oslo Sunday 28 March, 00:30 CET.
    entry, entity = await make_calendar(hass, aioclient_mock)
    rows = [
        event_row(
            id="earlier",
            start="2027-03-28T00:00:00+01:00",
            end="2027-03-28T00:15:00+01:00",
        ),
        event_row(id="all-day", start="2027-03-28", end="2027-03-29"),
        event_row(
            id="dst-one",
            start="2027-03-28T01:30:00+01:00",
            end="2027-03-28T03:30:00+02:00",
        ),
        event_row(
            id="dst-two",
            start="2027-03-28T01:30:00+01:00",
            end="2027-03-28T03:30:00+02:00",
        ),
        event_row(
            id="overnight",
            start="2027-03-28T23:30:00+02:00",
            end="2027-03-29T00:30:00+02:00",
        ),
        event_row(
            id="tomorrow",
            start="2027-03-29T16:00:00+02:00",
            end="2027-03-29T17:00:00+02:00",
        ),
        event_row(
            id="outside",
            start="2027-03-30T00:00:00+02:00",
            end="2027-03-30T01:00:00+02:00",
        ),
    ]
    events_mock = AsyncMock(
        return_value={"events": rows, "serverNow": dt_util.utcnow().isoformat()}
    )
    monkeypatch.setattr(type(entry.runtime_data.client), "async_events", events_mock)
    await entity.async_update()
    _, start, end = events_mock.await_args.args
    assert start.isoformat() == "2027-03-28T00:00:00+01:00"
    assert end.isoformat() == "2027-04-28T00:00:00+02:00"
    agenda = entity.extra_state_attributes["agenda"]
    assert [day["date"] for day in agenda] == ["2027-03-28", "2027-03-29"]
    assert {row["id"] for row in agenda[0]["events"]} == {
        "earlier",
        "all-day",
        "dst-one",
        "dst-two",
        "overnight",
    }
    assert {row["id"] for row in agenda[1]["events"]} == {"overnight", "tomorrow"}
    all_day = next(row for row in agenda[0]["events"] if row["id"] == "all-day")
    assert all_day["start"] == "2027-03-28"
    assert all_day["allDay"]
    assert entity.event.uid != "earlier"
    events_mock.side_effect = SamvevConnectionError("Offline")
    with pytest.raises(HomeAssistantError):
        await entity.async_update()
    assert entity.extra_state_attributes["stale"]
    assert entity.extra_state_attributes["agenda"] == agenda
    entry.runtime_data.coordinator.data = {}
    entity._handle_coordinator_update()  # noqa: SLF001
    assert entity.extra_state_attributes is None
    assert entity.event is None


async def test_imported_current_projection_clamps_to_complete_source_window(
    hass, aioclient_mock, monkeypatch, freezer
) -> None:
    """Small source windows work without pretending an unfetched range is empty."""
    freezer.move_to("2027-03-27T23:30:00Z")
    entry, _ = await make_calendar(hass, aioclient_mock)
    events_mock = AsyncMock(
        return_value={"events": [], "serverNow": dt_util.utcnow().isoformat()}
    )
    monkeypatch.setattr(type(entry.runtime_data.client), "async_events", events_mock)
    data = entry.runtime_data.coordinator.data
    data["calendars"].append(
        {
            "id": "source-one",
            "name": "Synthetic imported",
            "writable": False,
            "freshness": "current",
            "lastCompleteWindow": {
                "from": "2027-03-27T00:00:00Z",
                "to": "2027-04-01T00:00:00Z",
            },
        }
    )
    entry.runtime_data.coordinator.async_set_updated_data(data)
    await hass.async_block_till_done(wait_background_tasks=True)
    imported = hass.data[DATA_COMPONENT].get_entity("calendar.samvev_ha_source_one")
    assert imported.available
    calls = [
        call for call in events_mock.await_args_list if call.args[0] == "source-one"
    ]
    assert calls[-1].args[1].isoformat() == "2027-03-28T00:00:00+01:00"
    assert calls[-1].args[2].isoformat() == "2027-04-01T00:00:00+00:00"
    data["calendars"][-1]["lastCompleteWindow"]["to"] = "2027-03-29T10:00:00Z"
    with pytest.raises(HomeAssistantError):
        await imported.async_update()
    assert not imported.available


async def test_changed_sharing_clears_agenda_before_refetch_completes(
    hass, aioclient_mock, monkeypatch
) -> None:
    """Narrower grants must not display a former reader's cached plan."""
    import asyncio  # noqa: PLC0415

    entry, entity = await make_calendar(hass, aioclient_mock)
    now = dt_util.utcnow()
    rows = [
        event_row(
            start=(now + timedelta(hours=1)).isoformat(),
            end=(now + timedelta(hours=2)).isoformat(),
        )
    ]
    events_mock = AsyncMock(return_value={"events": rows, "serverNow": now.isoformat()})
    monkeypatch.setattr(type(entry.runtime_data.client), "async_events", events_mock)
    await entity.async_update()
    assert any(day["events"] for day in entity.extra_state_attributes["agenda"])
    ready = asyncio.Event()

    async def blocked(*_args):
        await ready.wait()
        return {"events": [], "serverNow": now.isoformat()}

    events_mock.side_effect = blocked
    entry.runtime_data.coordinator.connection["grants"]["revision"] += 1
    entry.runtime_data.coordinator.async_set_updated_data(
        entry.runtime_data.coordinator.data
    )
    assert not any(day["events"] for day in entity.extra_state_attributes["agenda"])
    assert entity.event is None
    assert not entity.available
    ready.set()
    await hass.async_block_till_done(wait_background_tasks=True)


async def test_delayed_private_response_is_discarded_after_nonempty_policy_change(
    hass, aioclient_mock, monkeypatch
) -> None:
    """An old private payload cannot repopulate caches under a newer policy."""
    import asyncio  # noqa: PLC0415

    entry, entity = await make_calendar(hass, aioclient_mock)
    coordinator = entry.runtime_data.coordinator
    started, release = asyncio.Event(), asyncio.Event()
    now = dt_util.utcnow()
    private = event_row(
        id="private-old-reader",
        summary="Former reader private plan",
        start=(now + timedelta(hours=1)).isoformat(),
        end=(now + timedelta(hours=2)).isoformat(),
    )
    permitted = event_row(
        id="permitted-new-reader",
        summary="New reader permitted plan",
        start=(now + timedelta(hours=3)).isoformat(),
        end=(now + timedelta(hours=4)).isoformat(),
    )
    calls = 0

    async def delayed(*_args):
        nonlocal calls
        calls += 1
        if calls == 1:
            started.set()
            await release.wait()
            rows = [private]
        else:
            rows = [permitted]
        return {"events": rows, "serverNow": now.isoformat()}

    monkeypatch.setattr(type(entry.runtime_data.client), "async_events", delayed)
    entity._refresh_task = entry.async_create_background_task(  # noqa: SLF001
        hass,
        entity._async_refresh_current(),  # noqa: SLF001
        "test delayed old policy",
    )
    await started.wait()
    coordinator.connection["grants"] = {
        **coordinator.connection["grants"],
        "revision": 2,
        "household": False,
        "personIds": ["new-synthetic-reader"],
    }
    coordinator.async_set_updated_data(coordinator.data)
    assert entity.event is None
    assert not any(day["events"] for day in entity.extra_state_attributes["agenda"])
    release.set()
    await hass.async_block_till_done(wait_background_tasks=True)
    assert calls == 2  # Immediate retry under the new, still nonempty policy.
    assert entity.event.uid == "permitted-new-reader"
    assert "private-old-reader" not in entity._events  # noqa: SLF001
    assert "Former reader private plan" not in str(entity.extra_state_attributes)
    assert entity.available


async def test_direct_interval_read_refuses_response_after_policy_revision_changes(
    hass, aioclient_mock, monkeypatch
) -> None:
    """User-initiated calendar range reads also reject an obsolete response."""
    entry, entity = await make_calendar(hass, aioclient_mock)
    coordinator = entry.runtime_data.coordinator
    now = dt_util.utcnow()

    async def changed_while_reading(*_args):
        coordinator.connection["grants"] = {
            **coordinator.connection["grants"],
            "revision": 2,
            "household": False,
            "personIds": ["new-synthetic-reader"],
        }
        return {"events": [event_row(id="old-private")], "serverNow": now.isoformat()}

    monkeypatch.setattr(
        type(entry.runtime_data.client), "async_events", changed_while_reading
    )
    with pytest.raises(HomeAssistantError):
        await entity.async_get_events(hass, now, now + timedelta(days=1))
    assert "old-private" not in entity._events  # noqa: SLF001
