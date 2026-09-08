"""Config flow for the Samvev integration."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

from .api import (
    SamvevAuthenticationError,
    SamvevClient,
    SamvevConnectionError,
    SamvevInvalidResponseError,
    normalize_base_url,
)
from .const import CONF_API_TOKEN, CONF_BASE_URL, DEFAULT_REQUEST_TIMEOUT, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_BASE_URL): TextSelector(
            TextSelectorConfig(type=TextSelectorType.URL)
        ),
        vol.Required(CONF_API_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        ),
    }
)

REAUTH_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }
)


class SamvevConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a Samvev config flow."""

    VERSION = 1

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Start reauthentication after an API authentication failure."""
        self._reauth_base_url = entry_data[CONF_BASE_URL]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and save a replacement API token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            client = SamvevClient(
                self._reauth_base_url,
                user_input[CONF_API_TOKEN],
                async_get_clientsession(self.hass),
                timeout=DEFAULT_REQUEST_TIMEOUT,
            )
            try:
                health = await client.async_health()
            except SamvevAuthenticationError:
                errors["base"] = "invalid_auth"
            except SamvevConnectionError:
                errors["base"] = "cannot_connect"
            except SamvevInvalidResponseError:
                errors["base"] = "invalid_response"
            except Exception:
                _LOGGER.exception("Unexpected error while reauthenticating Samvev")
                errors["base"] = "unknown"
            else:
                entry = self._get_reauth_entry()
                unique_id = (
                    health.instance_id or entry.unique_id or self._reauth_base_url
                )
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={CONF_API_TOKEN: user_input[CONF_API_TOKEN]},
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=REAUTH_SCHEMA,
            errors=errors,
        )

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Validate and create a Samvev config entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            try:
                base_url = normalize_base_url(user_input[CONF_BASE_URL])
                client = SamvevClient(
                    base_url,
                    user_input[CONF_API_TOKEN],
                    async_get_clientsession(self.hass),
                    timeout=DEFAULT_REQUEST_TIMEOUT,
                )
                health = await client.async_health()
            except ValueError:
                errors["base"] = "invalid_url"
            except SamvevAuthenticationError:
                errors["base"] = "invalid_auth"
            except SamvevConnectionError:
                errors["base"] = "cannot_connect"
            except SamvevInvalidResponseError:
                errors["base"] = "invalid_response"
            except Exception:
                _LOGGER.exception("Unexpected error while connecting to Samvev")
                errors["base"] = "unknown"
            else:
                unique_id = health.instance_id or base_url
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()
                title = health.name or urlsplit(base_url).netloc
                return self.async_create_entry(
                    title=title,
                    data={
                        CONF_BASE_URL: base_url,
                        CONF_API_TOKEN: user_input[CONF_API_TOKEN],
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_SCHEMA,
            errors=errors,
        )
