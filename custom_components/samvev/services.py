"""Generic Home Assistant actions exposed by the Samvev adapter."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

import voluptuous as vol
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import SupportsResponse, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse

    from .runtime import SamvevRuntimeData

from .api import SamvevApiError, SamvevAuthenticationError
from .const import (
    ATTR_CONFIG_ENTRY_ID,
    ATTR_CONTEXT,
    ATTR_DATA,
    ATTR_ENTITY_IDS,
    ATTR_EVENT_TYPE,
    ATTR_PROMPT,
    DOMAIN,
    SERVICE_ASK,
    SERVICE_EVENT,
)

ASK_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_PROMPT): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional(ATTR_CONTEXT): dict,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)

EVENT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_EVENT_TYPE): vol.All(cv.string, vol.Length(min=1)),
        vol.Optional(ATTR_DATA, default=dict): dict,
        vol.Optional(ATTR_ENTITY_IDS, default=list): cv.entity_ids,
        vol.Optional(ATTR_CONFIG_ENTRY_ID): cv.string,
    }
)


@callback
def async_register_actions(hass: HomeAssistant) -> None:
    """Register integration actions once for the HA process."""
    if hass.services.has_service(DOMAIN, SERVICE_ASK):
        return

    hass.services.async_register(
        DOMAIN,
        SERVICE_ASK,
        _async_ask,
        schema=ASK_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
    hass.services.async_register(
        DOMAIN,
        SERVICE_EVENT,
        _async_event,
        schema=EVENT_SCHEMA,
    )


async def _async_ask(call: ServiceCall) -> ServiceResponse:
    """Send a query and return Samvev's structured answer."""
    runtime = _runtime_for_call(call.hass, call)
    try:
        response = await runtime.client.async_ask(
            call.data[ATTR_PROMPT], call.data.get(ATTR_CONTEXT)
        )
    except SamvevApiError as err:
        raise _action_error(err) from err
    result: dict[str, Any] = {"answer": response.answer}
    if response.request_id is not None:
        result["request_id"] = response.request_id
    if response.data is not None:
        result["data"] = response.data
    return result


async def _async_event(call: ServiceCall) -> None:
    """Send one structured event plus explicitly selected HA states."""
    runtime = _runtime_for_call(call.hass, call)
    adapter_context = _selected_entity_context(call.hass, call.data[ATTR_ENTITY_IDS])
    try:
        response = await runtime.client.async_send_event(
            call.data[ATTR_EVENT_TYPE],
            dict(call.data[ATTR_DATA]),
            adapter_context,
        )
    except SamvevApiError as err:
        raise _action_error(err) from err
    if not response.accepted:
        raise HomeAssistantError(
            translation_domain=DOMAIN,
            translation_key="event_rejected",
        )
    await runtime.coordinator.async_request_refresh()


def _selected_entity_context(
    hass: HomeAssistant, entity_ids: list[str]
) -> dict[str, Any] | None:
    """Snapshot only the entities explicitly supplied to the action."""
    if not entity_ids:
        return None
    snapshots: list[dict[str, str]] = []
    missing: list[str] = []
    for entity_id in entity_ids:
        state = hass.states.get(entity_id)
        if state is None:
            missing.append(entity_id)
            continue
        snapshots.append(
            {
                "entity_id": entity_id,
                "state": state.state,
                "last_changed": state.last_changed.isoformat(),
            }
        )
    if missing:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entities_not_found",
            translation_placeholders={"entity_ids": ", ".join(missing)},
        )
    return {"entities": snapshots}


def _runtime_for_call(hass: HomeAssistant, call: ServiceCall) -> SamvevRuntimeData:
    """Resolve the explicitly selected or sole loaded config entry."""
    requested_id = call.data.get(ATTR_CONFIG_ENTRY_ID)
    if requested_id is not None:
        candidate = hass.config_entries.async_get_entry(requested_id)
        entries = [candidate] if candidate is not None else []
    else:
        entries = [
            entry
            for entry in hass.config_entries.async_entries(DOMAIN)
            if entry.state is ConfigEntryState.LOADED
        ]

    if len(entries) != 1 or entries[0].domain != DOMAIN:
        translation_key = (
            "entry_not_found"
            if requested_id is not None or not entries
            else "entry_required"
        )
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key=translation_key,
        )
    entry = cast("ConfigEntry[SamvevRuntimeData]", entries[0])
    if entry.state is not ConfigEntryState.LOADED:
        raise ServiceValidationError(
            translation_domain=DOMAIN,
            translation_key="entry_not_loaded",
        )
    return entry.runtime_data


def _action_error(err: SamvevApiError) -> HomeAssistantError:
    """Convert client failures to safe, user-visible HA errors."""
    key = (
        "action_invalid_auth"
        if isinstance(err, SamvevAuthenticationError)
        else "action_failed"
    )
    return HomeAssistantError(translation_domain=DOMAIN, translation_key=key)
