"""Tests for the Samvev config flow."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries, data_entry_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samvev.api import (
    HealthStatus,
    SamvevAuthenticationError,
    SamvevConnectionError,
    SamvevInvalidResponseError,
)
from custom_components.samvev.const import CONF_API_TOKEN, CONF_BASE_URL, DOMAIN

USER_INPUT = {
    CONF_BASE_URL: "https://samvev.example/",
    CONF_API_TOKEN: "secret-token",
}


async def test_user_flow_creates_entry(hass) -> None:
    """Validate the server and store normalized connection data."""
    with (
        patch(
            "custom_components.samvev.config_flow.SamvevClient.async_health",
            return_value=HealthStatus("ok", "instance-1", "Family Samvev"),
        ),
        patch("custom_components.samvev.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
        await hass.async_block_till_done()

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["title"] == "Family Samvev"
    assert result["data"] == {
        CONF_BASE_URL: "https://samvev.example",
        CONF_API_TOKEN: "secret-token",
    }
    assert result["result"].unique_id == "instance-1"


@pytest.mark.parametrize(
    ("error", "flow_error"),
    [
        (SamvevAuthenticationError("no"), "invalid_auth"),
        (SamvevConnectionError("offline"), "cannot_connect"),
        (SamvevInvalidResponseError("bad"), "invalid_response"),
    ],
)
async def test_user_flow_reports_connection_errors(hass, error, flow_error) -> None:
    """Keep the form open with a useful error for known API failures."""
    with patch(
        "custom_components.samvev.config_flow.SamvevClient.async_health",
        side_effect=error,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": flow_error}


async def test_user_flow_rejects_invalid_url_without_request(hass) -> None:
    """Reject credentials in URLs before constructing a request."""
    with patch(
        "custom_components.samvev.config_flow.SamvevClient.async_health"
    ) as health:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**USER_INPUT, CONF_BASE_URL: "https://user:pass@samvev.example"},
        )

    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_url"}
    health.assert_not_awaited()


async def test_duplicate_instance_aborts(hass) -> None:
    """Do not configure the same Samvev instance twice."""
    existing = MockConfigEntry(
        data=USER_INPUT,
        domain=DOMAIN,
        source=config_entries.SOURCE_USER,
        title="Existing",
        unique_id="instance-1",
    )
    existing.add_to_hass(hass)
    with patch(
        "custom_components.samvev.config_flow.SamvevClient.async_health",
        return_value=HealthStatus("ok", "instance-1"),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )

    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "already_configured"
