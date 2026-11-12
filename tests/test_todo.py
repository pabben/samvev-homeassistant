"""Shopping list entities use native HA actions and confirmed server results."""

import pytest
from homeassistant.components.todo import TodoItem, TodoItemStatus
from homeassistant.components.todo.const import TodoListEntityFeature
from homeassistant.exceptions import HomeAssistantError

from custom_components.samvev.todo import SamvevTodo

from .test_services import BASE_URL, setup_entry, snapshot


async def test_native_todo_actions_and_no_optimistic_write(
    hass, aioclient_mock
) -> None:
    """Create/check/rename/reopen/delete with observed revisions and no rewards."""
    entry = await setup_entry(hass, aioclient_mock)
    state = hass.states.get("todo.samvev_ha_groceries")
    assert state.state == "1"
    aioclient_mock.post(
        f"{BASE_URL}/api/v1/ha/lists/groceries/items",
        json={"item": {"id": "bread", "revision": 1}},
        status=201,
    )
    await hass.services.async_call(
        "todo",
        "add_item",
        {"entity_id": state.entity_id, "item": "Bread"},
        blocking=True,
    )
    assert hass.states.get(state.entity_id).state == "1"  # Snapshot is authoritative.
    aioclient_mock.patch(
        f"{BASE_URL}/api/v1/ha/lists/groceries/items/milk",
        json={"item": {"id": "milk", "revision": 5}},
    )
    await hass.services.async_call(
        "todo",
        "update_item",
        {
            "entity_id": state.entity_id,
            "item": "milk",
            "status": "completed",
            "rename": "Oat milk",
        },
        blocking=True,
    )
    request = next(
        call for call in aioclient_mock.mock_calls if call[0].upper() == "PATCH"
    )
    assert request[2]["expectedRevision"] == 4
    assert request[2]["checked"] is True
    assert request[2]["label"] == "Oat milk"
    assert not any(key in request[2] for key in ("xp", "reward", "approve"))
    entity = SamvevTodo(entry, entry.runtime_data.coordinator, snapshot()["lists"][0])
    await entity.async_update_todo_item(
        TodoItem(uid="milk", status=TodoItemStatus.NEEDS_ACTION)
    )
    assert [call for call in aioclient_mock.mock_calls if call[0].upper() == "PATCH"][
        -1
    ][2]["checked"] is False
    aioclient_mock.delete(
        f"{BASE_URL}/api/v1/ha/lists/groceries/items/milk",
        json={"item": {"id": "milk", "revision": 5}},
    )
    await entity.async_delete_todo_items(["milk"])


async def test_readonly_and_revoked_list_clear_items(hass, aioclient_mock) -> None:
    """No write features beyond the model; removed grants clear to-do content."""
    entry = await setup_entry(hass, aioclient_mock)
    coordinator = entry.runtime_data.coordinator
    row = snapshot()["lists"][0]
    entity = SamvevTodo(entry, coordinator, row)
    assert entity.supported_features == (
        TodoListEntityFeature.CREATE_TODO_ITEM
        | TodoListEntityFeature.UPDATE_TODO_ITEM
        | TodoListEntityFeature.DELETE_TODO_ITEM
    )
    coordinator.data["lists"][0]["writable"] = False
    assert entity.supported_features == 0
    with pytest.raises(HomeAssistantError):
        await entity.async_create_todo_item(TodoItem(summary="Forbidden"))
    coordinator.data = {}
    assert entity.todo_items is None
    assert not entity.available


async def test_missing_item_and_conflict_no_silent_retry(hass, aioclient_mock) -> None:
    """A stale edit refreshes and errors without silently replacing the winner."""
    entry = await setup_entry(hass, aioclient_mock)
    entity = SamvevTodo(entry, entry.runtime_data.coordinator, snapshot()["lists"][0])
    with pytest.raises(HomeAssistantError):
        await entity.async_update_todo_item(TodoItem(uid="missing", summary="New"))
    aioclient_mock.patch(f"{BASE_URL}/api/v1/ha/lists/groceries/items/milk", status=409)
    with pytest.raises(HomeAssistantError):
        await entity.async_update_todo_item(TodoItem(uid="milk", summary="New"))
    assert (
        len([call for call in aioclient_mock.mock_calls if call[0].upper() == "PATCH"])
        == 1
    )
