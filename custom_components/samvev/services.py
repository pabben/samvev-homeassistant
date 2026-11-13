"""Narrow message actions using the Samvev connection as actor."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast
from urllib.parse import quote

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .api import SamvevApiError, SamvevAuthenticationError, SamvevConflictError
from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse

    from .coordinator import SamvevDataUpdateCoordinator
    from .runtime import SamvevRuntimeData

SERVICES = ("create_message", "update_message", "withdraw_message")

AUDIENCE_SCHEMA = vol.Schema(
    {
        vol.Required("household"): cv.boolean,
        vol.Required("person_ids", default=list): [cv.string],
    }
)
COMMON: dict[Any, Any] = {
    vol.Optional("config_entry_id"): cv.string,
    vol.Optional("request_key"): vol.All(cv.string, vol.Length(min=8, max=128)),
}
CREATE_SCHEMA = vol.Schema(
    {
        **COMMON,
        vol.Required("body"): vol.All(cv.string, vol.Length(min=1, max=1000)),
        vol.Required("expires_at"): cv.string,
        vol.Required("audience"): AUDIENCE_SCHEMA,
        vol.Optional("importance", default="normal"): vol.In(("normal", "attention")),
        vol.Optional("publish_at"): cv.string,
    }
)
UPDATE_SCHEMA = vol.Schema(
    {
        **COMMON,
        vol.Required("message_id"): cv.string,
        vol.Optional("expected_revision"): cv.positive_int,
        vol.Optional("body"): vol.All(cv.string, vol.Length(min=1, max=1000)),
        vol.Optional("expires_at"): cv.string,
        vol.Optional("audience"): AUDIENCE_SCHEMA,
        vol.Optional("importance"): vol.In(("normal", "attention")),
        vol.Optional("publish_at"): cv.string,
    }
)
WITHDRAW_SCHEMA = vol.Schema(
    {
        **COMMON,
        vol.Required("message_id"): cv.string,
        vol.Optional("expected_revision"): cv.positive_int,
    }
)


@callback
def async_register_actions(hass: HomeAssistant) -> None:
    """Register narrow message actions once per HA process."""
    for name, handler, schema in (
        ("create_message", _async_create_message, CREATE_SCHEMA),
        ("update_message", _async_update_message, UPDATE_SCHEMA),
        ("withdraw_message", _async_withdraw_message, WITHDRAW_SCHEMA),
    ):
        if not hass.services.has_service(DOMAIN, name):
            hass.services.async_register(
                DOMAIN,
                name,
                handler,
                schema=schema,
                supports_response=SupportsResponse.OPTIONAL,
            )


@callback
def async_unregister_actions(hass: HomeAssistant) -> None:
    """Remove process-wide actions when the final entry unloads."""
    for name in SERVICES:
        hass.services.async_remove(DOMAIN, name)


async def async_mutate(
    coordinator: SamvevDataUpdateCoordinator,
    method: str,
    path: str,
    payload: dict[str, Any],
    request_key: str | None = None,
) -> dict[str, Any]:
    """Translate safe API errors after the coordinator handles refresh/retry."""
    try:
        return await coordinator.async_mutate(
            method, path, payload, request_key=request_key
        )
    except SamvevAuthenticationError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="action_invalid_auth"
        ) from err
    except SamvevConflictError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="conflict"
        ) from err
    except SamvevApiError as err:
        raise HomeAssistantError(
            translation_domain=DOMAIN, translation_key="action_failed"
        ) from err


def _payload(data: dict[str, Any]) -> dict[str, Any]:
    payload = {
        target: data[source]
        for source, target in (
            ("body", "body"),
            ("importance", "importance"),
            ("publish_at", "publishAt"),
            ("expires_at", "expiresAt"),
        )
        if source in data
    }
    if "audience" in data:
        payload["audience"] = {
            "household": data["audience"]["household"],
            "personIds": data["audience"]["person_ids"],
        }
    return payload


def _expected_revision(runtime: SamvevRuntimeData, data: dict[str, Any]) -> int:
    if "expected_revision" in data:
        return int(data["expected_revision"])
    row = next(
        (
            row
            for row in (runtime.coordinator.data or {}).get("messages", [])
            if row["id"] == data["message_id"]
        ),
        None,
    )
    if row is None:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="item_not_found"
        )
    return int(row["revision"])


async def _async_create_message(call: ServiceCall) -> ServiceResponse:
    runtime = _runtime_for_call(call.hass, call)
    return await async_mutate(
        runtime.coordinator,
        "POST",
        "messages",
        _payload(call.data),
        call.data.get("request_key"),
    )


async def _async_update_message(call: ServiceCall) -> ServiceResponse:
    runtime = _runtime_for_call(call.hass, call)
    payload = _payload(call.data)
    payload["expectedRevision"] = _expected_revision(runtime, call.data)
    return await async_mutate(
        runtime.coordinator,
        "PATCH",
        f"messages/{quote(call.data['message_id'], safe='')}",
        payload,
        call.data.get("request_key"),
    )


async def _async_withdraw_message(call: ServiceCall) -> ServiceResponse:
    runtime = _runtime_for_call(call.hass, call)
    return await async_mutate(
        runtime.coordinator,
        "POST",
        f"messages/{quote(call.data['message_id'], safe='')}/withdraw",
        {"expectedRevision": _expected_revision(runtime, call.data)},
        call.data.get("request_key"),
    )


def _runtime_for_call(hass: HomeAssistant, call: ServiceCall) -> SamvevRuntimeData:
    """Require unambiguous connection selection without impersonating HA users."""
    requested = call.data.get("config_entry_id")
    if requested:
        candidate = hass.config_entries.async_get_entry(requested)
        entries = [candidate] if candidate and candidate.domain == DOMAIN else []
    else:
        entries = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]
    if len(entries) != 1:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_required" if len(entries) > 1 else "entry_not_found",
        )
    entry = cast("ConfigEntry[SamvevRuntimeData]", entries[0])
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="entry_not_loaded"
        )
    return entry.runtime_data
