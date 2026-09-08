"""Tests for the isolated Samvev API client."""

from http import HTTPStatus

import pytest
from aiohttp import ClientConnectionError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from custom_components.samvev.api import (
    SamvevAuthenticationError,
    SamvevClient,
    SamvevConnectionError,
    SamvevInvalidResponseError,
    normalize_base_url,
)

BASE_URL = "https://samvev.example/root"
TOKEN = "super-secret-token"  # noqa: S105


async def test_client_contract_and_authorization(hass, aioclient_mock) -> None:
    """Exercise health, context, ask, and event against mocked HTTP."""
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/health",
        json={"status": "ok", "instance_id": "instance-1", "name": "Home"},
    )
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/context",
        json={
            "status": "connected",
            "attention_count": 1,
            "next_attention": {
                "id": "attention-1",
                "summary": "Bring the required equipment",
                "due_at": "2026-09-09T08:00:00Z",
                "kind": "reminder",
            },
        },
    )
    aioclient_mock.post(
        f"{BASE_URL}/api/v1/ask",
        json={"answer": "One item", "request_id": "request-1", "data": {"n": 1}},
    )
    aioclient_mock.post(
        f"{BASE_URL}/api/v1/events",
        json={"accepted": True, "event_id": "event-1"},
    )
    client = SamvevClient(BASE_URL, TOKEN, async_get_clientsession(hass))

    health = await client.async_health()
    context = await client.async_get_context()
    answer = await client.async_ask("What needs attention?", {"day": "tomorrow"})
    acknowledgement = await client.async_send_event(
        "household.context_changed",
        {"reason": "automation"},
        {"entities": [{"entity_id": "weather.home", "state": "rainy"}]},
    )

    assert health.instance_id == "instance-1"
    assert context.next_attention is not None
    assert context.next_attention.kind == "reminder"
    assert answer.answer == "One item"
    assert acknowledgement.accepted
    assert aioclient_mock.mock_calls[2][2] == {
        "prompt": "What needs attention?",
        "context": {"day": "tomorrow"},
    }
    assert aioclient_mock.mock_calls[3][2] == {
        "type": "household.context_changed",
        "data": {"reason": "automation"},
        "source": "home_assistant",
        "context": {"entities": [{"entity_id": "weather.home", "state": "rainy"}]},
    }
    assert all(
        call[3]["Authorization"] == f"Bearer {TOKEN}"
        for call in aioclient_mock.mock_calls
    )
    assert TOKEN not in repr(client)


async def test_context_endpoint_is_optional(hass, aioclient_mock) -> None:
    """Treat a missing projection endpoint as connected with unknown values."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/context", status=HTTPStatus.NOT_FOUND)
    client = SamvevClient(BASE_URL, TOKEN, async_get_clientsession(hass))

    context = await client.async_get_context()

    assert context.status == "connected"
    assert context.next_attention is None
    assert context.attention_count is None


@pytest.mark.parametrize(
    ("status", "response", "expected_exception"),
    [
        (HTTPStatus.UNAUTHORIZED, None, SamvevAuthenticationError),
        (HTTPStatus.OK, [], SamvevInvalidResponseError),
        (HTTPStatus.OK, {"wrong": "shape"}, SamvevInvalidResponseError),
    ],
)
async def test_health_errors(
    hass, aioclient_mock, status, response, expected_exception
) -> None:
    """Map authentication and invalid response failures to client exceptions."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/health", status=status, json=response)
    client = SamvevClient(BASE_URL, TOKEN, async_get_clientsession(hass))

    with pytest.raises(expected_exception):
        await client.async_health()


async def test_connection_error_is_sanitized(hass, aioclient_mock) -> None:
    """Do not carry the token into connection errors."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/health", exc=ClientConnectionError(TOKEN))
    client = SamvevClient(BASE_URL, TOKEN, async_get_clientsession(hass))

    with pytest.raises(SamvevConnectionError) as raised:
        await client.async_health()

    assert TOKEN not in str(raised.value)


@pytest.mark.parametrize(
    "value",
    [
        "",
        "samvev.example",
        "ftp://samvev.example",
        "https://user:pass@samvev.example",
        "https://samvev.example?token=secret",
        "https://samvev.example:invalid",
    ],
)
def test_normalize_base_url_rejects_invalid_values(value) -> None:
    """Reject unsafe and ambiguous base URLs."""
    with pytest.raises(ValueError, match="Base URL"):
        normalize_base_url(value)


def test_normalize_base_url() -> None:
    """Preserve a deployment path while removing trailing slashes."""
    assert normalize_base_url(" HTTPS://samvev.example/root/// ") == BASE_URL
