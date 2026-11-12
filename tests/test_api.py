"""Tests for the bounded, authenticated Samvev bridge client."""

from datetime import UTC, datetime

import pytest
from aiohttp import ClientConnectionError
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import (
    AiohttpClientMockResponse,
)

from custom_components.samvev.api import (
    MAX_RESPONSE_BYTES,
    SamvevAuthenticationError,
    SamvevClient,
    SamvevConflictError,
    SamvevConnectionError,
    SamvevInvalidResponseError,
    SamvevRequestError,
    normalize_base_url,
)

from .conftest import BASE_URL, TOKEN


async def test_protocol_and_bearer(hass, aioclient_mock, connection, snapshot):
    """Read authorized protocol data and send a revision-bound mutation."""
    prefix = f"{BASE_URL}/api/v1/ha"
    aioclient_mock.get(f"{prefix}/connection", json=connection)
    aioclient_mock.get(f"{prefix}/snapshot", json=snapshot)
    aioclient_mock.patch(
        f"{prefix}/lists/groceries/items/item-1",
        json={"item": {"id": "item-1", "revision": 2}},
    )
    client = SamvevClient(BASE_URL, TOKEN, async_get_clientsession(hass))
    assert await client.async_connection() == connection
    assert await client.async_snapshot() == snapshot
    payload = {
        "checked": True,
        "expectedRevision": 1,
        "requestKey": "synthetic-operation-1",
    }
    result = await client.async_mutate("PATCH", "lists/groceries/items/item-1", payload)
    assert result["item"]["revision"] == 2
    assert aioclient_mock.mock_calls[-1][2] == payload
    assert all(
        call[3]["Authorization"] == f"Bearer {TOKEN}"
        for call in aioclient_mock.mock_calls
    )
    assert TOKEN not in repr(client)


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        (401, SamvevAuthenticationError),
        (403, SamvevAuthenticationError),
        (409, SamvevConflictError),
        (500, SamvevConnectionError),
        (429, SamvevConnectionError),
        (404, SamvevRequestError),
        (302, SamvevRequestError),
    ],
)
async def test_errors_and_redirects_never_expose_body(
    hass, aioclient_mock, status, expected
):
    """Reject redirects and errors without leaking bodies or tokens."""
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/ha/connection",
        status=status,
        text=TOKEN,
        headers={"Location": "https://other.invalid/"},
    )
    client = SamvevClient(BASE_URL, TOKEN, async_get_clientsession(hass))
    with pytest.raises(expected) as raised:
        await client.async_connection()
    assert TOKEN not in str(raised.value)
    assert aioclient_mock.call_count == 1


@pytest.mark.parametrize(
    "response", [{}, {"schemaVersion": 2}, [], {"schemaVersion": True}]
)
async def test_invalid_handshake(hass, aioclient_mock, response):
    """Health alone is insufficient; require the bridge authority handshake."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/ha/connection", json=response)
    client = SamvevClient(BASE_URL, TOKEN, async_get_clientsession(hass))
    with pytest.raises(SamvevInvalidResponseError):
        await client.async_connection()


@pytest.mark.parametrize("field", ["lists", "messages", "calendars", "serverNow"])
async def test_incomplete_snapshot_is_not_empty_success(
    hass, aioclient_mock, snapshot, field
):
    """A malformed or missing collection cannot clear previously valid data."""
    snapshot.pop(field)
    aioclient_mock.get(f"{BASE_URL}/api/v1/ha/snapshot", json=snapshot)
    client = SamvevClient(BASE_URL, TOKEN, async_get_clientsession(hass))
    with pytest.raises(SamvevInvalidResponseError):
        await client.async_snapshot()


async def test_bounded_body(hass, aioclient_mock):
    """Reject an oversized response before decoding or exposing content."""
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/ha/connection", text="x" * (MAX_RESPONSE_BYTES + 1)
    )
    client = SamvevClient(BASE_URL, TOKEN, async_get_clientsession(hass))
    with pytest.raises(SamvevInvalidResponseError, match="too large"):
        await client.async_connection()


async def test_network_error_sanitized(hass, aioclient_mock):
    """Transport exception messages must not expose credentials."""
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/ha/connection", exc=ClientConnectionError(TOKEN)
    )
    client = SamvevClient(BASE_URL, TOKEN, async_get_clientsession(hass))
    with pytest.raises(SamvevConnectionError) as raised:
        await client.async_connection()
    assert TOKEN not in str(raised.value)


async def test_events_interval(hass, aioclient_mock):
    """Request the complete calendar interval instead of the next event."""
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/ha/calendars/samvev/events",
        json={"events": [], "serverNow": "2026-11-12T00:00:00Z"},
    )
    client = SamvevClient(BASE_URL, TOKEN, async_get_clientsession(hass))
    start = datetime(2026, 3, 28, tzinfo=UTC)
    end = datetime(2026, 3, 30, tzinfo=UTC)
    assert (await client.async_events("samvev", start, end))["events"] == []
    assert aioclient_mock.mock_calls[-1][1].query["start"] == start.isoformat()
    with pytest.raises(ValueError, match="aware"):
        await client.async_events("samvev", start.replace(tzinfo=None), end)


async def test_mutation_requires_safe_path_and_retry_key(hass):
    """Never let action inputs change the authenticated API destination."""
    client = SamvevClient(BASE_URL, TOKEN, async_get_clientsession(hass))
    with pytest.raises(ValueError, match="Unsupported"):
        await client.async_mutate(
            "POST", "https://other.invalid", {"requestKey": "12345678"}
        )
    with pytest.raises(ValueError, match="requestKey"):
        await client.async_mutate("POST", "messages", {})


@pytest.mark.parametrize(
    "value",
    [
        "",
        "samvev.example",
        "ftp://samvev.example",
        "https://user:pass@samvev.example",
        "https://samvev.example?token=secret",
        "https://samvev.example:invalid",
        "https://samvev.example/#token",
        "https://samvev.example/\\other",
    ],
)
def test_normalize_base_url_rejects_invalid_values(value):
    """Reject ambiguous roots and URLs containing credentials."""
    with pytest.raises(ValueError, match="Base URL"):
        normalize_base_url(value)


def test_normalize_base_url():
    """Preserve a deployment prefix and normalize trailing separators."""
    assert normalize_base_url(" HTTPS://samvev.example/root/// ") == f"{BASE_URL}/root"


@pytest.mark.parametrize(
    "changes",
    [
        {"start": "2026-10-25T02:30:00"},
        {"start": "2026-10-25", "end": "2026-10-26T00:00:00Z"},
        {"end": "2026-10-24T00:00:00Z"},
        {"revision": True},
        {"readOnly": "false"},
    ],
)
async def test_malformed_event_never_enters_calendar_cache(
    hass, aioclient_mock, changes
):
    """Require consistent dates, aware timestamps and authoritative revisions."""
    event = {
        "id": "event-1",
        "summary": "Synthetic appointment",
        "start": "2026-10-25T02:30:00+02:00",
        "end": "2026-10-25T02:30:00+01:00",
        "revision": 1,
        "readOnly": False,
        "source": "samvev",
        **changes,
    }
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/ha/calendars/samvev/events",
        json={"events": [event], "serverNow": "2026-10-25T00:00:00Z"},
    )
    client = SamvevClient(BASE_URL, TOKEN, async_get_clientsession(hass))
    with pytest.raises(SamvevInvalidResponseError):
        await client.async_events(
            "samvev",
            datetime(2026, 10, 24, tzinfo=UTC),
            datetime(2026, 10, 27, tzinfo=UTC),
        )


async def test_dst_and_all_day_event_shapes(hass, aioclient_mock):
    """Keep civil dates and simultaneous fall-back clock times distinct."""
    timed = {
        "id": "timed-1",
        "summary": "Synthetic timed",
        "start": "2026-10-25T02:30:00+02:00",
        "end": "2026-10-25T02:30:00+01:00",
        "revision": 1,
        "readOnly": True,
        "source": "google",
    }
    all_day = {
        "id": "all-day-1",
        "summary": "Synthetic all day",
        "start": "2026-10-25",
        "end": "2026-10-26",
        "revision": 1,
        "readOnly": False,
        "source": "samvev",
    }
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/ha/calendars/samvev/events",
        json={"events": [timed, all_day], "serverNow": "2026-10-25T00:00:00Z"},
    )
    client = SamvevClient(BASE_URL, TOKEN, async_get_clientsession(hass))
    result = await client.async_events(
        "samvev", datetime(2026, 10, 24, tzinfo=UTC), datetime(2026, 10, 27, tzinfo=UTC)
    )
    assert result["events"] == [timed, all_day]


async def test_stream_bound_without_content_length(hass, aioclient_mock, monkeypatch):
    """An absent Content-Length does not bypass the decompressed body limit."""
    monkeypatch.setattr(
        AiohttpClientMockResponse, "content_length", property(lambda _: None)
    )
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/ha/connection", text="x" * (MAX_RESPONSE_BYTES + 1)
    )
    client = SamvevClient(BASE_URL, TOKEN, async_get_clientsession(hass))
    with pytest.raises(SamvevInvalidResponseError, match="too large"):
        await client.async_connection()
