"""Message count/attributes and explicit connection freshness sensors."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.const import EntityCategory
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .const import DOMAIN

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.core import CALLBACK_TYPE, HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SamvevConfigEntry
    from .coordinator import SamvevDataUpdateCoordinator


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: SamvevConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Expose multiple messages without placing text in a bounded state."""
    async_add_entities(
        SamvevSensor(entry, entry.runtime_data.coordinator, key)
        for key in ("messages", "connection_status", "last_success")
    )


class SamvevSensor(CoordinatorEntity["SamvevDataUpdateCoordinator"], SensorEntity):
    """Connection status or a complete active-message projection."""

    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"messages"})

    def __init__(
        self,
        entry: SamvevConfigEntry,
        coordinator: SamvevDataUpdateCoordinator,
        key: str,
    ) -> None:
        """Set immutable sensor identity and static metadata."""
        super().__init__(coordinator)
        self.key = key
        self._expiry_unsub: CALLBACK_TYPE | None = None
        self._attr_unique_id = f"{entry.unique_id or entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._object_id = slugify(key)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.unique_id or entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Samvev",
            "model": "Samvev connection",
        }
        if key == "messages":
            self._attr_icon = "mdi:message-text-outline"
        elif key == "last_success":
            self._attr_device_class = SensorDeviceClass.TIMESTAMP
            self._attr_entity_category = EntityCategory.DIAGNOSTIC
        else:
            self._attr_device_class = SensorDeviceClass.ENUM
            self._attr_options = ["connected", "disconnected"]
            self._attr_icon = "mdi:connection"
            self._attr_entity_category = EntityCategory.DIAGNOSTIC

    @property
    def suggested_object_id(self) -> str:
        """Suggest stable English object IDs, independent of UI locale."""
        return self._object_id

    @property
    def available(self) -> bool:
        """Keep diagnostic status visible when content is unavailable."""
        return self.key != "messages" or super().available

    @property
    def _messages(self) -> list[dict[str, Any]]:
        now = dt_util.utcnow()
        active = []
        for row in (self.coordinator.data or {}).get("messages", []):
            publish = dt_util.parse_datetime(row["publishAt"])
            expires = dt_util.parse_datetime(row["expiresAt"])
            if (
                publish is not None
                and expires is not None
                and publish <= now < expires
                and row["state"] not in {"withdrawn", "cancelled"}
            ):
                active.append(row)
        return active

    @property
    def native_value(self) -> str | int | datetime | None:
        """Return small states; message text is available only in attributes."""
        if self.key == "messages":
            return len(self._messages)
        if self.key == "last_success":
            return self.coordinator.last_success
        return "connected" if self.coordinator.last_update_success else "disconnected"

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose complete active rows and whether the projection is stale."""
        if self.key == "messages":
            return {
                "messages": self._messages,
                "stale": not self.coordinator.last_update_success,
            }
        if self.key == "connection_status":
            return {
                "last_success": self.coordinator.last_success.isoformat()
                if self.coordinator.last_success
                else None,
                "poll_interval_seconds": 30,
            }
        return None

    @callback
    def _schedule_expiry(self) -> None:
        if self._expiry_unsub:
            self._expiry_unsub()
            self._expiry_unsub = None
        expirations = [
            dt_util.parse_datetime(row["expiresAt"]) for row in self._messages
        ]
        if expirations:
            self._expiry_unsub = async_track_point_in_utc_time(
                self.hass,
                self._expire,
                min(value for value in expirations if value is not None),
            )

    @callback
    def _expire(self, _now: datetime) -> None:
        self._expiry_unsub = None
        self.async_write_ha_state()
        self._schedule_expiry()

    @callback
    def _handle_coordinator_update(self) -> None:
        super()._handle_coordinator_update()
        if self.key == "messages":
            self._schedule_expiry()

    async def async_added_to_hass(self) -> None:
        """Schedule local expiry even when the next poll is delayed."""
        await super().async_added_to_hass()
        if self.key == "messages":
            self._schedule_expiry()

    async def async_will_remove_from_hass(self) -> None:
        """Cancel local message expiry timers on unload."""
        if self._expiry_unsub:
            self._expiry_unsub()
            self._expiry_unsub = None
        await super().async_will_remove_from_hass()
