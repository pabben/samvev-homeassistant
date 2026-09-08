"""Constants for the Samvev integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "samvev"

CONF_BASE_URL = "base_url"
CONF_API_TOKEN = "api_token"  # noqa: S105

PLATFORMS = [Platform.SENSOR]

DEFAULT_SCAN_INTERVAL = timedelta(minutes=5)
DEFAULT_REQUEST_TIMEOUT = 10.0

SERVICE_ASK = "ask"
SERVICE_EVENT = "event"

ATTR_CONFIG_ENTRY_ID = "config_entry_id"
ATTR_PROMPT = "prompt"
ATTR_CONTEXT = "context"
ATTR_EVENT_TYPE = "event_type"
ATTR_DATA = "data"
ATTR_ENTITY_IDS = "entity_ids"
