"""Samvev shopping boards exposed through Home Assistant's to-do model."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import quote

from homeassistant.components.todo import TodoItem, TodoItemStatus, TodoListEntity
from homeassistant.components.todo.const import TodoListEntityFeature
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import slugify

from .const import DOMAIN
from .services import async_mutate

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SamvevConfigEntry
    from .coordinator import SamvevDataUpdateCoordinator


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: SamvevConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Discover explicitly shared lists, including later grant changes."""
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    @callback
    def discover() -> None:
        entities = []
        for row in (coordinator.data or {}).get("lists", []):
            if row["id"] not in known:
                known.add(row["id"])
                entities.append(SamvevTodo(entry, coordinator, row))
        async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


class SamvevTodo(CoordinatorEntity["SamvevDataUpdateCoordinator"], TodoListEntity):
    """A server-authoritative shopping list with revision-protected writes."""

    _attr_has_entity_name = True

    def __init__(
        self,
        entry: SamvevConfigEntry,
        coordinator: SamvevDataUpdateCoordinator,
        row: dict[str, Any],
    ) -> None:
        """Bind an entity to the stable server list identity."""
        super().__init__(coordinator)
        self.list_id = row["id"]
        self._attr_unique_id = (
            f"{entry.unique_id or entry.entry_id}_list_{self.list_id}"
        )
        self._attr_name = row["name"]
        self._object_id = slugify(self.list_id)
        self._attr_icon = "mdi:cart-outline"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.unique_id or entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Samvev",
            "model": "Samvev connection",
        }

    @property
    def suggested_object_id(self) -> str:
        """Suggest stable English object IDs, independent of UI locale."""
        return self._object_id

    @property
    def _list(self) -> dict[str, Any] | None:
        return next(
            (
                row
                for row in (self.coordinator.data or {}).get("lists", [])
                if row["id"] == self.list_id
            ),
            None,
        )

    @property
    def available(self) -> bool:
        """A removed grant makes the list unavailable immediately."""
        return super().available and self._list is not None

    @property
    def supported_features(self) -> TodoListEntityFeature:
        """Expose only the fields and writes supported by Samvev."""
        if not self._list or not self._list.get("writable"):
            return TodoListEntityFeature(0)
        return (
            TodoListEntityFeature.CREATE_TODO_ITEM
            | TodoListEntityFeature.UPDATE_TODO_ITEM
            | TodoListEntityFeature.DELETE_TODO_ITEM
        )

    @property
    def todo_items(self) -> list[TodoItem] | None:
        """Read current items without retaining revoked private content."""
        if not self._list:
            return None
        return [
            TodoItem(
                uid=row["id"],
                summary=row["label"],
                status=TodoItemStatus.COMPLETED
                if row["checked"]
                else TodoItemStatus.NEEDS_ACTION,
            )
            for row in self._list["items"]
        ]

    def _require_write(self) -> None:
        if not self.available or not self.supported_features:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="read_only"
            )

    def _item(self, uid: str | None) -> dict[str, Any]:
        row = next(
            (row for row in (self._list or {}).get("items", []) if row["id"] == uid),
            None,
        )
        if row is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="item_not_found"
            )
        return dict(row)

    @property
    def _path(self) -> str:
        return f"lists/{quote(self.list_id, safe='')}/items"

    async def async_create_todo_item(self, item: TodoItem) -> None:
        """Create an item and wait for Samvev's authoritative result."""
        self._require_write()
        await async_mutate(
            self.coordinator,
            "POST",
            self._path,
            {
                "label": item.summary,
                "checked": item.status == TodoItemStatus.COMPLETED,
            },
        )

    async def async_update_todo_item(self, item: TodoItem) -> None:
        """Apply only supplied fields using the last observed revision."""
        self._require_write()
        row = self._item(item.uid)
        payload: dict[str, Any] = {"expectedRevision": row["revision"]}
        if item.summary is not None:
            payload["label"] = item.summary
        if item.status is not None:
            payload["checked"] = item.status == TodoItemStatus.COMPLETED
        await async_mutate(
            self.coordinator,
            "PATCH",
            f"{self._path}/{quote(row['id'], safe='')}",
            payload,
        )

    async def async_delete_todo_items(self, uids: list[str]) -> None:
        """Delete each selected item with its own observed revision."""
        self._require_write()
        rows = [dict(self._item(uid)) for uid in uids]
        for row in rows:
            await async_mutate(
                self.coordinator,
                "DELETE",
                f"{self._path}/{quote(row['id'], safe='')}",
                {"expectedRevision": row["revision"]},
            )
