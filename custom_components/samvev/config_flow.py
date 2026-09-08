"""Config flow for the Samvev integration."""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urlsplit

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

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


class SamvevConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a Samvev config flow."""

    VERSION = 1

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
