"""The Samvev Home Assistant adapter."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.config_entries import ConfigEntry
from homeassistant.exceptions import ConfigEntryAuthFailed, ConfigEntryNotReady
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_get_clientsession

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.typing import ConfigType

from .api import (
    SamvevAuthenticationError,
    SamvevClient,
    SamvevConnectionError,
    SamvevInvalidResponseError,
)
from .const import (
    CONF_API_TOKEN,
    CONF_BASE_URL,
    DEFAULT_REQUEST_TIMEOUT,
    DOMAIN,
    PLATFORMS,
)
from .coordinator import SamvevDataUpdateCoordinator
from .runtime import SamvevRuntimeData
from .services import async_register_actions

_LOGGER = logging.getLogger(__name__)

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


type SamvevConfigEntry = ConfigEntry[SamvevRuntimeData]


async def async_setup(hass: HomeAssistant, _config: ConfigType) -> bool:
    """Set up integration-level Samvev actions."""
    async_register_actions(hass)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SamvevConfigEntry) -> bool:
    """Set up Samvev from a config entry."""
    client = SamvevClient(
        entry.data[CONF_BASE_URL],
        entry.data[CONF_API_TOKEN],
        async_get_clientsession(hass),
        timeout=DEFAULT_REQUEST_TIMEOUT,
    )

    try:
        await client.async_health()
    except SamvevAuthenticationError as err:
        raise ConfigEntryAuthFailed("Samvev rejected the API token") from err
    except (SamvevConnectionError, SamvevInvalidResponseError) as err:
        raise ConfigEntryNotReady(f"Unable to set up Samvev: {err}") from err

    coordinator = SamvevDataUpdateCoordinator(hass, entry, client)
    entry.runtime_data = SamvevRuntimeData(client, coordinator)
    await coordinator.async_config_entry_first_refresh()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    _LOGGER.debug("Connected to Samvev at %s", client.base_url)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: SamvevConfigEntry) -> bool:
    """Unload a Samvev config entry."""
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
