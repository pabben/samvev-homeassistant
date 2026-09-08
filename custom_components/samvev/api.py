"""Async client for the provisional Samvev HTTP API.

This module deliberately has no Home Assistant imports. It is the contract boundary
between the adapter and Samvev Core and can be extracted into a separate package if
the API stabilizes.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any, Final, Literal, overload
from urllib.parse import urlsplit, urlunsplit

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout

API_PREFIX: Final = "api/v1"


class SamvevApiError(Exception):
    """Base exception for Samvev client errors."""


class SamvevAuthenticationError(SamvevApiError):
    """The API token was rejected."""


class SamvevConnectionError(SamvevApiError):
    """The Samvev server could not be reached."""


class SamvevInvalidResponseError(SamvevApiError):
    """The server returned an invalid or unsupported response."""


@dataclass(frozen=True, slots=True)
class HealthStatus:
    """Samvev server health information."""

    status: str
    instance_id: str | None = None
    name: str | None = None


@dataclass(frozen=True, slots=True)
class AttentionItem:
    """A structured attention item decided by Samvev Core."""

    item_id: str | None
    summary: str
    due_at: str | None = None
    kind: str | None = None


@dataclass(frozen=True, slots=True)
class ContextStatus:
    """Small status projection exposed to adapter entities."""

    status: str
    next_attention: AttentionItem | None = None
    attention_count: int | None = None

    @classmethod
    def without_context_endpoint(cls) -> ContextStatus:
        """Return a compatible response for servers without context projection."""
        return cls(status="connected")


@dataclass(frozen=True, slots=True)
class AskResponse:
    """Response to a Samvev query."""

    answer: str
    request_id: str | None = None
    data: dict[str, Any] | None = None


@dataclass(frozen=True, slots=True)
class EventResponse:
    """Acknowledgement from Samvev for an incoming event."""

    accepted: bool
    event_id: str | None = None


class SamvevClient:
    """Small asynchronous client for Samvev Core."""

    __slots__ = ("_base_url", "_session", "_timeout", "_token")

    def __init__(
        self,
        base_url: str,
        api_token: str,
        session: ClientSession,
        *,
        timeout: float = 10.0,
    ) -> None:
        """Initialize the client without taking ownership of the HTTP session."""
        self._base_url = normalize_base_url(base_url)
        self._token = api_token
        self._session = session
        self._timeout = ClientTimeout(total=timeout)

    @property
    def base_url(self) -> str:
        """Return the normalized, non-secret base URL."""
        return self._base_url

    def __repr__(self) -> str:
        """Return a representation that never includes credentials."""
        return f"{type(self).__name__}(base_url={self._base_url!r})"

    async def async_health(self) -> HealthStatus:
        """Fetch and validate server health."""
        payload = await self._request("GET", "health")
        status = _required_string(payload, "status")
        if status not in {"ok", "healthy"}:
            raise SamvevInvalidResponseError("Samvev reported an unhealthy status")
        return HealthStatus(
            status=status,
            instance_id=_optional_string(payload, "instance_id"),
            name=_optional_string(payload, "name"),
        )

    async def async_get_context(self) -> ContextStatus:
        """Fetch the small, precomputed context projection used by HA entities."""
        payload = await self._request("GET", "context", allow_not_found=True)
        if payload is None:
            return ContextStatus.without_context_endpoint()

        attention_payload = payload.get("next_attention")
        next_attention: AttentionItem | None = None
        if attention_payload is not None:
            if not isinstance(attention_payload, dict):
                raise SamvevInvalidResponseError(
                    "Field 'next_attention' must be an object or null"
                )
            next_attention = AttentionItem(
                item_id=_optional_string(attention_payload, "id"),
                summary=_required_string(attention_payload, "summary"),
                due_at=_optional_string(attention_payload, "due_at"),
                kind=_optional_string(attention_payload, "kind"),
            )

        attention_count = payload.get("attention_count")
        if attention_count is not None and (
            not isinstance(attention_count, int) or isinstance(attention_count, bool)
        ):
            raise SamvevInvalidResponseError(
                "Field 'attention_count' must be an integer or null"
            )
        if isinstance(attention_count, int) and attention_count < 0:
            raise SamvevInvalidResponseError(
                "Field 'attention_count' must not be negative"
            )

        status = payload.get("status", "connected")
        if not isinstance(status, str) or not status:
            raise SamvevInvalidResponseError("Field 'status' must be a string")
        return ContextStatus(status, next_attention, attention_count)

    async def async_ask(
        self, prompt: str, context: dict[str, Any] | None = None
    ) -> AskResponse:
        """Send a query to Samvev and return its structured response."""
        request: dict[str, Any] = {"prompt": prompt}
        if context is not None:
            request["context"] = context
        payload = await self._request("POST", "ask", json_body=request)
        return AskResponse(
            answer=_required_string(payload, "answer"),
            request_id=_optional_string(payload, "request_id"),
            data=_optional_object(payload, "data"),
        )

    async def async_send_event(
        self,
        event_type: str,
        data: dict[str, Any],
        context: dict[str, Any] | None = None,
    ) -> EventResponse:
        """Send structured adapter input to Samvev."""
        request: dict[str, Any] = {
            "type": event_type,
            "data": data,
            "source": "home_assistant",
        }
        if context is not None:
            request["context"] = context
        payload = await self._request(
            "POST",
            "events",
            json_body=request,
        )
        accepted = payload.get("accepted")
        if not isinstance(accepted, bool):
            raise SamvevInvalidResponseError("Field 'accepted' must be a boolean")
        return EventResponse(
            accepted=accepted,
            event_id=_optional_string(payload, "event_id"),
        )

    @overload
    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        json_body: dict[str, Any] | None = None,
        allow_not_found: Literal[False] = False,
    ) -> dict[str, Any]: ...

    @overload
    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        json_body: dict[str, Any] | None = None,
        allow_not_found: Literal[True],
    ) -> dict[str, Any] | None: ...

    async def _request(
        self,
        method: str,
        endpoint: str,
        *,
        json_body: dict[str, Any] | None = None,
        allow_not_found: bool = False,
    ) -> dict[str, Any] | None:
        """Make one authenticated JSON request without exposing response bodies."""
        url = f"{self._base_url}/{API_PREFIX}/{endpoint}"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self._token}",
        }
        try:
            async with self._session.request(
                method,
                url,
                headers=headers,
                json=json_body,
                timeout=self._timeout,
            ) as response:
                if response.status in {
                    HTTPStatus.UNAUTHORIZED,
                    HTTPStatus.FORBIDDEN,
                }:
                    raise SamvevAuthenticationError("Samvev rejected the API token")
                if allow_not_found and response.status == HTTPStatus.NOT_FOUND:
                    return None
                if not (HTTPStatus.OK <= response.status < HTTPStatus.MULTIPLE_CHOICES):
                    raise SamvevConnectionError(
                        f"Samvev request failed with HTTP {response.status}"
                    )
                return await _read_json_object(response)
        except SamvevApiError:
            raise
        except (TimeoutError, ClientError) as err:
            raise SamvevConnectionError("Unable to reach the Samvev server") from err


def normalize_base_url(base_url: str) -> str:
    """Validate and normalize a Samvev base URL."""
    if not isinstance(base_url, str) or not (candidate := base_url.strip()):
        raise ValueError("Base URL is required")
    candidate = candidate.rstrip("/")
    parsed = urlsplit(candidate)
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("Base URL must be an HTTP(S) URL without credentials")
    try:
        _ = parsed.port
    except ValueError as err:
        raise ValueError("Base URL has an invalid port") from err
    normalized_path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme.lower(), parsed.netloc, normalized_path, "", ""))


async def _read_json_object(response: ClientResponse) -> dict[str, Any]:
    """Decode a response and require a JSON object."""
    try:
        payload = await response.json(content_type=None)
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise SamvevInvalidResponseError("Samvev returned malformed JSON") from err
    if not isinstance(payload, dict):
        raise SamvevInvalidResponseError("Samvev response must be a JSON object")
    return payload


def _required_string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SamvevInvalidResponseError(f"Field {key!r} must be a non-empty string")
    return value


def _optional_string(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise SamvevInvalidResponseError(f"Field {key!r} must be a string or null")
    return value


def _optional_object(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, dict):
        raise SamvevInvalidResponseError(f"Field {key!r} must be an object or null")
    return value
