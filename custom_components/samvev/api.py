"""Bounded asynchronous client for the versioned Samvev HA bridge API."""

from __future__ import annotations

import json
import re
from datetime import date, datetime
from http import HTTPStatus
from typing import Any, Final
from urllib.parse import quote, urlencode, urlsplit, urlunsplit

from aiohttp import ClientError, ClientResponse, ClientSession, ClientTimeout

API_PREFIX: Final = "api/v1/ha"
MAX_RESPONSE_BYTES: Final = 2 * 1024 * 1024
MIN_REQUEST_KEY: Final = 8
MAX_REQUEST_KEY: Final = 128
_MUTATION_PATH = re.compile(
    r"(?:lists/groceries/items(?:/[A-Za-z0-9_-]+)?|"
    r"messages(?:/[A-Za-z0-9_-]+(?:/withdraw)?)?|"
    r"calendars/samvev/events(?:/[A-Za-z0-9_-]+)?)\Z"
)


class SamvevApiError(Exception):
    """Base exception containing no server response or credential."""


class SamvevAuthenticationError(SamvevApiError):
    """The connection no longer has the required authorization."""


class SamvevConnectionError(SamvevApiError):
    """The authoritative result could not be obtained; retry may be safe."""


class SamvevInvalidResponseError(SamvevApiError):
    """The response violates the supported bridge contract."""


class SamvevConflictError(SamvevApiError):
    """Samvev rejected a stale revision or mismatched retry key."""


class SamvevRequestError(SamvevApiError):
    """Samvev definitively rejected a request."""


class SamvevClient:
    """HTTP transport; HA owns its session and Samvev owns all content."""

    __slots__ = ("_base_url", "_session", "_timeout", "_token")

    def __init__(
        self,
        base_url: str,
        api_token: str,
        session: ClientSession,
        *,
        timeout: float = 10.0,
    ) -> None:
        """Initialize without taking ownership of the HTTP session."""
        self._base_url = normalize_base_url(base_url)
        self._token = api_token
        self._session = session
        self._timeout = ClientTimeout(total=timeout)

    @property
    def base_url(self) -> str:
        """Return the normalized URL without credentials."""
        return self._base_url

    def __repr__(self) -> str:
        """Exclude the secret and the potentially private server address."""
        return f"{type(self).__name__}()"

    async def async_connection(self) -> dict[str, Any]:
        """Authenticate and validate the stable connection and its authority."""
        payload = await self._request("GET", "connection")
        _validate_connection(payload)
        return payload

    async def async_snapshot(self) -> dict[str, Any]:
        """Read the complete authoritative current, permitted projection."""
        payload = await self._request("GET", "snapshot")
        _validate_connection(payload)
        _instant(payload, "serverNow")
        for listing in _objects(payload, "lists"):
            _string(listing, "id")
            _string(listing, "name")
            _boolean(listing, "writable")
            for item in _objects(listing, "items"):
                _string(item, "id")
                _string(item, "label")
                _boolean(item, "checked")
                _revision(item)
        for message in _objects(payload, "messages"):
            for field in (
                "id",
                "body",
                "authorName",
                "authorType",
                "importance",
                "state",
            ):
                _string(message, field)
            _instant(message, "publishAt")
            _instant(message, "expiresAt")
            _revision(message)
            audience = message.get("audience")
            if not isinstance(audience, dict):
                raise SamvevInvalidResponseError("Invalid message audience")
            _boolean(audience, "household")
            _strings(audience, "personIds")
        for calendar in _objects(payload, "calendars"):
            _string(calendar, "id")
            _string(calendar, "name")
            _boolean(calendar, "writable")
        return payload

    async def async_events(
        self, calendar_id: str, start: datetime, end: datetime
    ) -> dict[str, Any]:
        """Read every permitted event in a requested bounded interval."""
        if start.tzinfo is None or end.tzinfo is None or end <= start:
            raise ValueError("An aware increasing calendar interval is required")
        query = urlencode({"start": start.isoformat(), "end": end.isoformat()})
        payload = await self._request(
            "GET", f"calendars/{quote(calendar_id, safe='')}/events?{query}"
        )
        for event in _objects(payload, "events"):
            _validate_event(event)
        _instant(payload, "serverNow")
        return payload

    async def async_mutate(
        self, method: str, endpoint: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Send an idempotent mutation with the caller's durable request key."""
        if method not in {"POST", "PATCH", "DELETE"} or not _MUTATION_PATH.fullmatch(
            endpoint
        ):
            raise ValueError("Unsupported Samvev mutation")
        key = payload.get("requestKey")
        if (
            not isinstance(key, str)
            or not MIN_REQUEST_KEY <= len(key) <= MAX_REQUEST_KEY
        ):
            raise ValueError("A stable requestKey is required")
        result = await self._request(method, endpoint, json_body=payload)
        field = (
            "message"
            if endpoint.startswith("messages")
            else "event"
            if endpoint.startswith("calendars")
            else "item"
        )
        resource = result.get(field)
        if not isinstance(resource, dict):
            raise SamvevInvalidResponseError("Missing authoritative mutation result")
        _string(resource, "id")
        _revision(resource)
        return result

    async def _request(
        self, method: str, endpoint: str, *, json_body: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Make one bounded request; never redirect or expose response bodies."""
        url = f"{self._base_url}/{API_PREFIX}/{endpoint}"
        try:
            async with self._session.request(
                method,
                url,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self._token}",
                },
                json=json_body,
                timeout=self._timeout,
                allow_redirects=False,
            ) as response:
                if response.status in {HTTPStatus.UNAUTHORIZED, HTTPStatus.FORBIDDEN}:
                    raise SamvevAuthenticationError("Samvev authorization rejected")
                if response.status == HTTPStatus.CONFLICT:
                    raise SamvevConflictError("Samvev revision or retry conflict")
                if (
                    response.status >= HTTPStatus.INTERNAL_SERVER_ERROR
                    or response.status == HTTPStatus.TOO_MANY_REQUESTS
                ):
                    raise SamvevConnectionError("Samvev temporarily unavailable")
                if not HTTPStatus.OK <= response.status < HTTPStatus.MULTIPLE_CHOICES:
                    raise SamvevRequestError("Samvev request rejected")
                return await _read_json_object(response)
        except SamvevApiError:
            raise
        except (TimeoutError, ClientError):
            raise SamvevConnectionError("Unable to reach Samvev") from None


def normalize_base_url(base_url: str) -> str:
    """Validate an HTTP(S) deployment root without embedded credentials."""
    if not isinstance(base_url, str) or not (candidate := base_url.strip()):
        raise ValueError("Base URL is required")
    parsed = urlsplit(candidate.rstrip("/"))
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or any(char.isspace() or not char.isprintable() for char in candidate)
        or "\\" in candidate
    ):
        raise ValueError("Base URL must be HTTP(S) without credentials")
    try:
        _ = parsed.port
    except ValueError as err:
        raise ValueError("Base URL has an invalid port") from err
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc, parsed.path.rstrip("/"), "", "")
    )


async def _read_json_object(response: ClientResponse) -> dict[str, Any]:
    """Read a bounded body before decoding, including streamed responses."""
    if (
        response.content_length is not None
        and response.content_length > MAX_RESPONSE_BYTES
    ):
        raise SamvevInvalidResponseError("Samvev response too large")
    body = bytearray()
    async for chunk in response.content.iter_chunked(64 * 1024):
        body.extend(chunk)
        if len(body) > MAX_RESPONSE_BYTES:
            raise SamvevInvalidResponseError("Samvev response too large")
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError) as err:
        raise SamvevInvalidResponseError("Samvev returned malformed JSON") from err
    if not isinstance(payload, dict):
        raise SamvevInvalidResponseError("Samvev response must be an object")
    return payload


def _string(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise SamvevInvalidResponseError("Invalid string field")
    return value


def _boolean(payload: dict[str, Any], key: str) -> None:
    if not isinstance(payload.get(key), bool):
        raise SamvevInvalidResponseError("Invalid boolean field")


def _revision(payload: dict[str, Any], key: str = "revision", minimum: int = 1) -> None:
    value = payload.get(key)
    if type(value) is not int or value < minimum:
        raise SamvevInvalidResponseError("Invalid revision")


def _strings(payload: dict[str, Any], key: str) -> None:
    value = payload.get(key)
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise SamvevInvalidResponseError("Invalid string collection")


def _objects(payload: dict[str, Any], key: str) -> list[dict[str, Any]]:
    value = payload.get(key)
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise SamvevInvalidResponseError("Invalid object collection")
    return value


def _instant(payload: dict[str, Any], key: str) -> None:
    try:
        value = datetime.fromisoformat(_string(payload, key))
    except ValueError as err:
        raise SamvevInvalidResponseError("Invalid timestamp") from err
    if value.tzinfo is None:
        raise SamvevInvalidResponseError("Timestamp must contain a timezone")


def _validate_connection(payload: dict[str, Any]) -> None:
    if type(payload.get("schemaVersion")) is not int or payload["schemaVersion"] != 1:
        raise SamvevInvalidResponseError("Unsupported Samvev bridge version")
    for field in ("installationId", "connectionId", "householdId", "name", "timezone"):
        _string(payload, field)
    _strings(payload, "capabilities")
    grants = payload.get("grants")
    if not isinstance(grants, dict):
        raise SamvevInvalidResponseError("Missing explicit sharing grants")
    _revision(grants, minimum=0)
    _boolean(grants, "household")
    for key in ("listIds", "personIds", "calendarSourceIds"):
        _strings(grants, key)


def _validate_event(event: dict[str, Any]) -> None:
    """Reject malformed dates and mixed all-day/timed events before caching."""
    for key in ("id", "summary", "source"):
        _string(event, key)
    _revision(event)
    _boolean(event, "readOnly")
    for key in ("description", "location"):
        if event.get(key) is not None and not isinstance(event[key], str):
            raise SamvevInvalidResponseError("Invalid event details")
    start_text, end_text = _string(event, "start"), _string(event, "end")
    try:
        start: date | datetime
        end: date | datetime
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", start_text) and re.fullmatch(
            r"\d{4}-\d{2}-\d{2}", end_text
        ):
            start, end = date.fromisoformat(start_text), date.fromisoformat(end_text)
        else:
            start, end = (
                datetime.fromisoformat(start_text),
                datetime.fromisoformat(end_text),
            )
            if start.tzinfo is None or end.tzinfo is None:
                raise ValueError("Timezone required")  # noqa: TRY301
        if end <= start:
            raise ValueError("Invalid interval")  # noqa: TRY301
    except (TypeError, ValueError):
        raise SamvevInvalidResponseError("Invalid event interval") from None
