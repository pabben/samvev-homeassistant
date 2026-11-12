"""GUI setup, reauthorization and endpoint migration tests."""

from unittest.mock import AsyncMock, patch

import pytest
from homeassistant import config_entries, data_entry_flow
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samvev.api import (
    SamvevAuthenticationError,
    SamvevConnectionError,
    SamvevInvalidResponseError,
)
from custom_components.samvev.const import CONF_API_TOKEN, CONF_BASE_URL, DOMAIN

from .conftest import BASE_URL, CONNECTION, TOKEN

USER_INPUT = {CONF_BASE_URL: f"{BASE_URL}/", CONF_API_TOKEN: TOKEN}
IDENTITY = "installation-1:connection-1"


def make_entry():
    """Return an entry bound to the exact machine connection."""
    return MockConfigEntry(
        domain=DOMAIN, data=USER_INPUT, title="Synthetic", unique_id=IDENTITY
    )


async def test_user_flow_creates_connection_bound_entry(hass, connection):
    """Create one entry per installation and connection, not per server URL."""
    with (
        patch(
            "custom_components.samvev.config_flow.SamvevClient.async_connection",
            return_value=connection,
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
    assert result["title"] == CONNECTION["name"]
    assert result["data"] == {CONF_BASE_URL: BASE_URL, CONF_API_TOKEN: TOKEN}
    assert result["result"].unique_id == IDENTITY


@pytest.mark.parametrize(
    ("error", "flow_error"),
    [
        (SamvevAuthenticationError("no"), "invalid_auth"),
        (SamvevConnectionError("offline"), "cannot_connect"),
        (SamvevInvalidResponseError("bad"), "invalid_response"),
    ],
)
async def test_flow_reports_known_failures(hass, error, flow_error):
    """Keep setup open when the token or supported protocol is invalid."""
    with patch(
        "custom_components.samvev.config_flow.SamvevClient.async_connection",
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


async def test_invalid_url_never_sends_token(hass):
    """Reject credentials in a URL before network I/O."""
    with patch(
        "custom_components.samvev.config_flow.SamvevClient.async_connection"
    ) as request:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {**USER_INPUT, CONF_BASE_URL: "https://user:pass@samvev.example"},
        )
    assert result["errors"] == {"base": "invalid_url"}
    request.assert_not_awaited()


async def test_duplicate_connection_aborts(hass, connection):
    """Keep stable IDs when the same connection is entered through a new URL."""
    make_entry().add_to_hass(hass)
    with patch(
        "custom_components.samvev.config_flow.SamvevClient.async_connection",
        return_value=connection,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": config_entries.SOURCE_USER}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], USER_INPUT
        )
    assert result["reason"] == "already_configured"


async def test_reauth_rotates_same_connection(hass, connection):
    """A replacement key is validated before updating and reloading the entry."""
    entry = make_entry()
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.samvev.config_flow.SamvevClient.async_connection",
            side_effect=[SamvevAuthenticationError(), connection],
        ),
        patch.object(
            hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
        ) as reload_entry,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_REAUTH,
                "entry_id": entry.entry_id,
                "unique_id": entry.unique_id,
            },
            data=entry.data,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_TOKEN: "invalid-token"}
        )
        assert result["errors"] == {"base": "invalid_auth"}
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_API_TOKEN: "replacement-token"}
        )
        await hass.async_block_till_done()
    assert result["reason"] == "reauth_successful"
    assert entry.data[CONF_API_TOKEN] == "replacement-token"
    reload_entry.assert_awaited_once_with(entry.entry_id)


async def test_reconfigure_url_preserves_identity(hass, connection):
    """Allow relocation only after the new endpoint authenticates same identity."""
    entry = make_entry()
    entry.add_to_hass(hass)
    with (
        patch(
            "custom_components.samvev.config_flow.SamvevClient.async_connection",
            return_value=connection,
        ),
        patch.object(
            hass.config_entries, "async_reload", new=AsyncMock(return_value=True)
        ),
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": config_entries.SOURCE_RECONFIGURE,
                "entry_id": entry.entry_id,
            },
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                CONF_BASE_URL: "https://relocated.example/root",
                CONF_API_TOKEN: "replacement-token",
            },
        )
        await hass.async_block_till_done()
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_BASE_URL] == "https://relocated.example/root"
    assert entry.unique_id == IDENTITY


@pytest.mark.parametrize(
    "source", [config_entries.SOURCE_REAUTH, config_entries.SOURCE_RECONFIGURE]
)
async def test_rotation_to_other_connection_rejected(hass, connection, source):
    """Never silently transfer existing dashboard entities to another household."""
    entry = make_entry()
    entry.add_to_hass(hass)
    connection["connectionId"] = "different-connection"
    with patch(
        "custom_components.samvev.config_flow.SamvevClient.async_connection",
        return_value=connection,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={
                "source": source,
                "entry_id": entry.entry_id,
                "unique_id": entry.unique_id,
            },
            data=entry.data if source == config_entries.SOURCE_REAUTH else None,
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            USER_INPUT
            if source == config_entries.SOURCE_RECONFIGURE
            else {CONF_API_TOKEN: TOKEN},
        )
    assert result["reason"] == "unique_id_mismatch"
    assert entry.data == USER_INPUT
