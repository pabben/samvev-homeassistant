"""The native Samvev Home Assistant integration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry, ConfigEntryState
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .api import SamvevApiError, SamvevAuthenticationError, SamvevClient
from .const import (
    CONF_API_TOKEN,
    CONF_BASE_URL,
    DEFAULT_REQUEST_TIMEOUT,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import SamvevDataUpdateCoordinator
from .runtime import SamvevRuntimeData
from .services import async_register_actions, async_unregister_actions

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
type SamvevConfigEntry = ConfigEntry[SamvevRuntimeData]


async def async_setup(_hass: HomeAssistant, _config: ConfigType) -> bool:
    """Initialize integration-level configuration."""
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SamvevConfigEntry) -> bool:
    """Validate machine authorization before exposing any shared content."""
    client = SamvevClient(
        entry.data[CONF_BASE_URL],
        entry.data[CONF_API_TOKEN],
        async_get_clientsession(hass),
        timeout=DEFAULT_REQUEST_TIMEOUT,
    )
    try:
        connection = await client.async_connection()
    except SamvevAuthenticationError:
        raise ConfigEntryAuthFailed("Samvev authorization rejected") from None
    except SamvevApiError:
        raise ConfigEntryNotReady("Unable to connect to the Samvev bridge") from None
    identity = f"{connection['installationId']}:{connection['connectionId']}"
    if entry.unique_id and entry.unique_id != identity:
        raise ConfigEntryAuthFailed("Samvev connection identity changed; reconfigure")
    coordinator = SamvevDataUpdateCoordinator(hass, entry, client, connection)
    entry.runtime_data = SamvevRuntimeData(client, coordinator)
    await coordinator.async_config_entry_first_refresh()
    async_register_actions(hass)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SamvevConfigEntry) -> bool:
    """Unload entities; coordinator listeners and polling shut down with entry."""
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded and not any(
        other.entry_id != entry.entry_id and other.state is ConfigEntryState.LOADED
        for other in hass.config_entries.async_entries(DOMAIN)
    ):
        async_unregister_actions(hass)
    return unloaded


async def async_remove_entry(hass: HomeAssistant, entry: SamvevConfigEntry) -> None:
    """Delete local retry metadata; never revoke remote credentials implicitly."""
    await Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.operations").async_remove()
