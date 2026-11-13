"""GUI setup, URL reconfiguration and machine-token reauthorization."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import voluptuous as vol
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import (
    SamvevApiError,
    SamvevAuthenticationError,
    SamvevClient,
    SamvevConnectionError,
    normalize_base_url,
)
from .const import CONF_API_TOKEN, CONF_BASE_URL, DEFAULT_REQUEST_TIMEOUT, DOMAIN

if TYPE_CHECKING:
    from collections.abc import Mapping


def _schema(base_url: str | None = None, *, token_only: bool = False) -> vol.Schema:
    fields = {
        vol.Required(CONF_API_TOKEN): TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
    }
    if not token_only:
        key = (
            vol.Required(CONF_BASE_URL, default=base_url)
            if base_url
            else vol.Required(CONF_BASE_URL)
        )
        fields[key] = TextSelector(TextSelectorConfig(type=TextSelectorType.URL))
    return vol.Schema(fields)


class SamvevConfigFlow(ConfigFlow, domain=DOMAIN):
    """Bind one HA entry to one separately revocable Samvev connection."""

    VERSION = 1

    async def _validate(
        self, base_url: str, token: str
    ) -> tuple[str | None, dict[str, Any] | None, str | None]:
        try:
            normalized = normalize_base_url(base_url)
            connection = await SamvevClient(
                normalized,
                token,
                async_get_clientsession(self.hass),
                timeout=DEFAULT_REQUEST_TIMEOUT,
            ).async_connection()
        except ValueError:
            return None, None, "invalid_url"
        except SamvevAuthenticationError:
            return None, None, "invalid_auth"
        except SamvevConnectionError:
            return None, None, "cannot_connect"
        except SamvevApiError:
            return None, None, "invalid_response"
        return normalized, connection, None

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Verify the bridge protocol and bearer authority before creating entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url, connection, error = await self._validate(
                user_input[CONF_BASE_URL], user_input[CONF_API_TOKEN]
            )
            if error:
                errors["base"] = error
            else:
                if connection is None or base_url is None:
                    raise RuntimeError("Missing validated connection")
                await self.async_set_unique_id(
                    f"{connection['installationId']}:{connection['connectionId']}"
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=connection["name"],
                    data={
                        CONF_BASE_URL: base_url,
                        CONF_API_TOKEN: user_input[CONF_API_TOKEN],
                    },
                )
        return self.async_show_form(
            step_id="user", data_schema=_schema(), errors=errors
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        """Ask for a replacement machine credential for this connection."""
        self._reauth_base_url = entry_data[CONF_BASE_URL]
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Keep stable identity while replacing a rejected or expired token."""
        errors: dict[str, str] = {}
        if user_input is not None:
            _, connection, error = await self._validate(
                self._reauth_base_url, user_input[CONF_API_TOKEN]
            )
            if error:
                errors["base"] = error
            else:
                if connection is None:
                    raise RuntimeError("Missing validated connection")
                await self.async_set_unique_id(
                    f"{connection['installationId']}:{connection['connectionId']}"
                )
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    self._get_reauth_entry(),
                    data_updates={CONF_API_TOKEN: user_input[CONF_API_TOKEN]},
                )
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=_schema(token_only=True),
            errors=errors,
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Move a server URL or rotate a token without replacing entity IDs."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            base_url, connection, error = await self._validate(
                user_input[CONF_BASE_URL], user_input[CONF_API_TOKEN]
            )
            if error:
                errors["base"] = error
            else:
                if connection is None or base_url is None:
                    raise RuntimeError("Missing validated connection")
                await self.async_set_unique_id(
                    f"{connection['installationId']}:{connection['connectionId']}"
                )
                self._abort_if_unique_id_mismatch()
                return self.async_update_reload_and_abort(
                    entry,
                    data_updates={
                        CONF_BASE_URL: base_url,
                        CONF_API_TOKEN: user_input[CONF_API_TOKEN],
                    },
                )
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_schema(entry.data[CONF_BASE_URL]),
            errors=errors,
        )
