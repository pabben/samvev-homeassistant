"""Sensors backed by Samvev's precomputed status projection."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from homeassistant.components.sensor import (
    SensorEntity,
    SensorEntityDescription,
)
from homeassistant.const import EntityCategory
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import CONF_BASE_URL, DOMAIN
from .coordinator import SamvevDataUpdateCoordinator

MAX_STATE_LENGTH = 255
ELLIPSIS = "..."

if TYPE_CHECKING:
    from collections.abc import Callable

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SamvevConfigEntry
    from .api import ContextStatus


@dataclass(frozen=True, kw_only=True)
class SamvevSensorEntityDescription(SensorEntityDescription):
    """Describe a Samvev sensor."""

    value_fn: Callable[[ContextStatus], str | int | None]


def _attention_summary(data: ContextStatus) -> str | None:
    """Fit a summary into HA state while retaining the full value as metadata."""
    if data.next_attention is None:
        return None
    summary = data.next_attention.summary
    if len(summary) <= MAX_STATE_LENGTH:
        return summary
    return f"{summary[: MAX_STATE_LENGTH - len(ELLIPSIS)]}{ELLIPSIS}"


SENSORS: tuple[SamvevSensorEntityDescription, ...] = (
    SamvevSensorEntityDescription(
        key="status",
        translation_key="status",
        icon="mdi:cloud-check-outline",
        entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda data: data.status,
    ),
    SamvevSensorEntityDescription(
        key="next_attention",
        translation_key="next_attention",
        icon="mdi:message-alert-outline",
        value_fn=_attention_summary,
    ),
    SamvevSensorEntityDescription(
        key="attention_count",
        translation_key="attention_count",
        icon="mdi:counter",
        native_unit_of_measurement="items",
        value_fn=lambda data: data.attention_count,
    ),
)


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: SamvevConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up Samvev sensors."""
    async_add_entities(
        SamvevSensor(entry, entry.runtime_data.coordinator, description)
        for description in SENSORS
    )


class SamvevSensor(CoordinatorEntity[SamvevDataUpdateCoordinator], SensorEntity):
    """Represent a value from Samvev's status projection."""

    _attr_has_entity_name = True
    entity_description: SamvevSensorEntityDescription

    def __init__(
        self,
        entry: SamvevConfigEntry,
        coordinator: SamvevDataUpdateCoordinator,
        description: SamvevSensorEntityDescription,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_{description.key}"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Samvev",
            "model": "Samvev API",
            "configuration_url": entry.data[CONF_BASE_URL],
        }

    @property
    def native_value(self) -> str | int | None:
        """Return the projected value."""
        return self.entity_description.value_fn(self.coordinator.data)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Expose only structured metadata for the next attention item."""
        if self.entity_description.key != "next_attention":
            return None
        item = self.coordinator.data.next_attention
        if item is None:
            return None
        return {
            "id": item.item_id,
            "summary": item.summary,
            "due_at": item.due_at,
            "kind": item.kind,
        }
