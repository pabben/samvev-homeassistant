"""Constants for the Samvev bridge integration."""

from datetime import timedelta

from homeassistant.const import Platform

DOMAIN = "samvev"
CONF_BASE_URL = "base_url"
CONF_API_TOKEN = "api_token"  # noqa: S105
PLATFORMS = [Platform.SENSOR, Platform.TODO, Platform.CALENDAR]
DEFAULT_SCAN_INTERVAL = timedelta(seconds=30)
DEFAULT_REQUEST_TIMEOUT = 10.0
ATTR_CONFIG_ENTRY_ID = "config_entry_id"
