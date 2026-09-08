"""Tests for privacy-preserving diagnostics."""

import json

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.samvev.const import CONF_API_TOKEN, CONF_BASE_URL, DOMAIN
from custom_components.samvev.diagnostics import async_get_config_entry_diagnostics

BASE_URL = "https://samvev.example"
TOKEN = "never-export-this-token"  # noqa: S105


async def test_diagnostics_redacts_token_and_attention_content(
    hass, aioclient_mock
) -> None:
    """Export operational facts without secrets or personal reminder text."""
    aioclient_mock.get(f"{BASE_URL}/api/v1/health", json={"status": "ok"})
    aioclient_mock.get(
        f"{BASE_URL}/api/v1/context",
        json={
            "status": "connected",
            "attention_count": 1,
            "next_attention": {
                "id": "private-id",
                "summary": "private reminder content",
            },
        },
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Samvev test",
        data={CONF_BASE_URL: BASE_URL, CONF_API_TOKEN: TOKEN},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    serialized = json.dumps(diagnostics)

    assert TOKEN not in serialized
    assert "private reminder content" not in serialized
    assert "private-id" not in serialized
    assert diagnostics["context_projection"]["attention_present"] is True
    assert diagnostics["context_projection"]["attention_count"] == 1
