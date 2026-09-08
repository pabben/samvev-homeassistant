"""Data coordinator for the small Samvev status projection."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

from .api import (
    ContextStatus,
    SamvevAuthenticationError,
    SamvevClient,
    SamvevConnectionError,
    SamvevInvalidResponseError,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


class SamvevDataUpdateCoordinator(DataUpdateCoordinator[ContextStatus]):
    """Poll only Samvev's precomputed context projection."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: SamvevClient,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
            always_update=False,
        )
        self.client = client

    async def _async_update_data(self) -> ContextStatus:
        """Fetch the structured status projection."""
        try:
            return await self.client.async_get_context()
        except SamvevAuthenticationError as err:
            raise ConfigEntryAuthFailed("Samvev rejected the API token") from err
        except (SamvevConnectionError, SamvevInvalidResponseError) as err:
            raise UpdateFailed(f"Unable to update Samvev status: {err}") from err
