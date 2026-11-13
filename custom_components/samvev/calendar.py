"""Native and imported Samvev calendars using HA's standard calendar API."""

from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import TYPE_CHECKING, Any
from urllib.parse import quote
from zoneinfo import ZoneInfo

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.components.calendar.const import CalendarEntityFeature
from homeassistant.core import callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .api import SamvevApiError, SamvevAuthenticationError
from .const import DOMAIN
from .services import async_mutate

if TYPE_CHECKING:
    from asyncio import Task

    from homeassistant.core import HomeAssistant
    from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

    from . import SamvevConfigEntry
    from .coordinator import SamvevDataUpdateCoordinator


MAX_POLICY_REFRESH_ATTEMPTS = 2


class _AuthorityChangedError(HomeAssistantError):
    """A response belongs to a sharing policy that is no longer current."""


async def async_setup_entry(
    _hass: HomeAssistant,
    entry: SamvevConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Discover only explicitly shared calendars."""
    coordinator = entry.runtime_data.coordinator
    known: set[str] = set()

    @callback
    def discover() -> None:
        entities = []
        for row in (coordinator.data or {}).get("calendars", []):
            if row["id"] not in known:
                known.add(row["id"])
                entities.append(SamvevCalendar(entry, coordinator, row))
        async_add_entities(entities)

    discover()
    entry.async_on_unload(coordinator.async_add_listener(discover))


def _parse_time(value: str) -> date | datetime:
    if len(value) == len("YYYY-MM-DD"):
        return date.fromisoformat(value)
    parsed = dt_util.parse_datetime(value)
    if parsed is None or parsed.tzinfo is None:
        raise ValueError("Calendar timestamp must include a timezone")
    return parsed


def _event(row: dict[str, Any]) -> CalendarEvent:
    return CalendarEvent(
        uid=row["id"],
        summary=row["summary"],
        start=_parse_time(row["start"]),
        end=_parse_time(row["end"]),
        description=row.get("description") or None,
        location=row.get("location") or None,
    )


class SamvevCalendar(CoordinatorEntity["SamvevDataUpdateCoordinator"], CalendarEntity):
    """A full-window calendar with per-event server revision protection."""

    _attr_has_entity_name = True
    _unrecorded_attributes = frozenset({"agenda"})

    def __init__(
        self,
        entry: SamvevConfigEntry,
        coordinator: SamvevDataUpdateCoordinator,
        row: dict[str, Any],
    ) -> None:
        """Initialize without claiming imported calendars are writable."""
        super().__init__(coordinator)
        self.calendar_id = row["id"]
        self._entry = entry
        self._refresh_task: Task[None] | None = None
        self._attr_unique_id = (
            f"{entry.unique_id or entry.entry_id}_calendar_{self.calendar_id}"
        )
        self._attr_name = row["name"]
        self._object_id = slugify(self.calendar_id)
        self._attr_device_info = {
            "identifiers": {(DOMAIN, entry.unique_id or entry.entry_id)},
            "name": entry.title,
            "manufacturer": "Samvev",
            "model": "Samvev connection",
        }
        self._events: dict[str, dict[str, Any]] = {}
        self._read_available = True
        self._current_events: list[CalendarEvent] = []
        self._projection_authority = self._authority_fingerprint()

    @property
    def suggested_object_id(self) -> str:
        """Suggest stable English object IDs, independent of UI locale."""
        return self._object_id

    @property
    def _calendar(self) -> dict[str, Any] | None:
        return next(
            (
                row
                for row in (self.coordinator.data or {}).get("calendars", [])
                if row["id"] == self.calendar_id
            ),
            None,
        )

    def _authority_fingerprint(self) -> str:
        """Snapshot identity and authority before crossing an HTTP await."""
        connection = self.coordinator.connection
        row = self._calendar
        return json.dumps(
            {
                "installationId": connection.get("installationId"),
                "connectionId": connection.get("connectionId"),
                "timezone": connection.get("timezone"),
                "grants": connection.get("grants"),
                "capabilities": connection.get("capabilities"),
                "calendar": {"id": row["id"], "writable": row["writable"]}
                if row
                else None,
            },
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def available(self) -> bool:
        """Never expose a calendar after its grant is removed."""
        return super().available and self._calendar is not None and self._read_available

    @property
    def supported_features(self) -> CalendarEntityFeature:
        """Advertise supported writes only for the native calendar."""
        if (
            self.calendar_id != "samvev"
            or not self._calendar
            or not self._calendar.get("writable")
        ):
            return CalendarEntityFeature(0)
        return (
            CalendarEntityFeature.CREATE_EVENT
            | CalendarEntityFeature.UPDATE_EVENT
            | CalendarEntityFeature.DELETE_EVENT
        )

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        """Keep upstream cache freshness separate from bridge connectivity."""
        row = self._calendar
        if row is None:
            return None
        return {
            "read_only": not row.get("writable", False),
            "source_freshness": row.get("freshness"),
            "source_status": row.get("status"),
            "last_source_sync": row.get("lastSyncSucceededAt"),
            "source_error": row.get("errorCode"),
            "last_complete_window": row.get("lastCompleteWindow"),
            "stale": not self.available or row.get("freshness") in {"pending", "stale"},
            "agenda": self._agenda,
        }

    @property
    def _agenda(self) -> list[dict[str, Any]]:
        """Group the current interval cache into two household civil days."""
        if not self._calendar:
            return []
        zone = ZoneInfo(self.coordinator.connection["timezone"])
        today = dt_util.utcnow().astimezone(zone).date()
        days: list[dict[str, Any]] = []
        for offset in range(2):
            day = today + timedelta(days=offset)
            next_day = day + timedelta(days=1)
            start = datetime.combine(day, time.min, zone)
            end = datetime.combine(next_day, time.min, zone)
            rows = []
            for event in self._current_events:
                if event.all_day:
                    overlaps = event.start < next_day and event.end > day
                else:
                    overlaps = event.start < end and event.end > start
                if overlaps:
                    rows.append(
                        {
                            "id": event.uid,
                            "summary": event.summary,
                            "start": event.start.isoformat(),
                            "end": event.end.isoformat(),
                            "allDay": event.all_day,
                            "location": event.location,
                        }
                    )
            days.append({"date": day.isoformat(), "events": rows})
        return days

    @property
    def event(self) -> CalendarEvent | None:
        """Return the current/next event, not a substitute for interval queries."""
        if not self._calendar:
            return None
        now = dt_util.now()
        return next(
            (event for event in self._current_events if event.end_datetime_local > now),
            None,
        )

    async def async_get_events(
        self,
        _hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return all permitted overlapping events in the exact requested range."""
        if not self._calendar:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="read_only"
            )
        authority = self._authority_fingerprint()
        try:
            payload = await self.coordinator.client.async_events(
                self.calendar_id, start_date, end_date
            )
        except SamvevAuthenticationError as err:
            self._events.clear()
            self._current_events.clear()
            self._read_available = False
            self.async_write_ha_state()
            await self.coordinator.async_request_refresh()
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="action_invalid_auth"
            ) from err
        except SamvevApiError as err:
            self._read_available = False
            self.async_write_ha_state()
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="action_failed"
            ) from err
        if not self._calendar or self.coordinator.authorization_revoked:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="action_invalid_auth"
            )
        if self._authority_fingerprint() != authority:
            # An old in-flight response must never restore a removed reader's
            # content after a newer policy snapshot cleared the cache.
            raise _AuthorityChangedError(
                translation_domain=DOMAIN, translation_key="action_failed"
            )
        rows = payload["events"]
        events = sorted(
            (_event(row) for row in rows), key=lambda event: event.start_datetime_local
        )
        self._read_available = True
        # Keep observed revisions; never fetch newer ones merely to force a write.
        self._events.update({row["id"]: row for row in rows})
        return events

    async def async_update(self) -> None:
        """Update the current-event projection; interval reads remain independent."""
        if not self._calendar:
            self._events.clear()
            self._current_events.clear()
            return
        zone = ZoneInfo(self.coordinator.connection["timezone"])
        today = dt_util.utcnow().astimezone(zone).date()
        start = datetime.combine(today, time.min, zone)
        end = start + timedelta(days=31)
        if self.calendar_id != "samvev":
            # Do not ask an imported source for an unsynchronized 31-day range.
            # Today and tomorrow must both be complete before projecting them.
            window = self._calendar.get("lastCompleteWindow")
            complete_start = dt_util.parse_datetime(window["from"]) if window else None
            complete_end = dt_util.parse_datetime(window["to"]) if window else None
            if (
                complete_start is None
                or complete_end is None
                or complete_start > start
                or complete_end < start + timedelta(days=2)
            ):
                self._read_available = False
                self.async_write_ha_state()
                raise HomeAssistantError(
                    translation_domain=DOMAIN, translation_key="action_failed"
                )
            end = min(end, complete_end)
        self._current_events = await self.async_get_events(self.hass, start, end)

    @callback
    def _handle_coordinator_update(self) -> None:
        authority = self._authority_fingerprint()
        sharing_changed = authority != self._projection_authority
        self._projection_authority = authority
        if not self._calendar or sharing_changed:
            self._read_available = False
            self._events.clear()
            self._current_events.clear()
        super()._handle_coordinator_update()
        if (
            self._calendar
            and self.coordinator.last_update_success
            and (self._refresh_task is None or self._refresh_task.done())
        ):
            self._refresh_task = self._entry.async_create_background_task(
                self.hass, self._async_refresh_current(), "refresh Samvev calendar"
            )

    async def _async_refresh_current(self) -> None:
        for _attempt in range(MAX_POLICY_REFRESH_ATTEMPTS):
            try:
                await self.async_update()
            except _AuthorityChangedError:
                # A policy update may arrive while this task is still running,
                # so the coordinator listener cannot start a replacement task.
                # Refetch under current authority instead of waiting one poll.
                if self._calendar and not self.coordinator.authorization_revoked:
                    continue
                return
            except HomeAssistantError:
                return
            self.async_write_ha_state()
            return

    async def async_added_to_hass(self) -> None:
        """Load current event after the entity has a HA context."""
        await super().async_added_to_hass()
        await self._async_refresh_current()

    def _require_write(self) -> None:
        if not self.available or not self.supported_features:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="read_only"
            )

    def _revision(self, uid: str) -> int:
        row = self._events.get(uid)
        if row is None:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="event_not_cached"
            )
        if row.get("readOnly", True):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="read_only"
            )
        return int(row["revision"])

    @staticmethod
    def _payload(values: dict[str, Any]) -> dict[str, Any]:
        if (
            values.get("rrule")
            or values.get("recurrence_id")
            or values.get("recurrence_range")
        ):
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unsupported_recurrence"
            )
        payload = {}
        for source, target in (
            ("summary", "summary"),
            ("dtstart", "start"),
            ("dtend", "end"),
            ("description", "description"),
            ("location", "location"),
        ):
            if source in values:
                value = values[source]
                payload[target] = (
                    value.isoformat() if isinstance(value, (date, datetime)) else value
                )
        return payload

    async def async_create_event(self, **kwargs: Any) -> None:  # noqa: ANN401
        """Create an own Samvev event; imported providers remain read-only."""
        self._require_write()
        await async_mutate(
            self.coordinator, "POST", "calendars/samvev/events", self._payload(kwargs)
        )

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Update using the exact revision observed by this entity."""
        self._require_write()
        if recurrence_id or recurrence_range:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unsupported_recurrence"
            )
        payload = self._payload(event)
        payload["expectedRevision"] = self._revision(uid)
        await async_mutate(
            self.coordinator,
            "PATCH",
            f"calendars/samvev/events/{quote(uid, safe='')}",
            payload,
        )

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Cancel an own event without modifying external source calendars."""
        self._require_write()
        if recurrence_id or recurrence_range:
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="unsupported_recurrence"
            )
        await async_mutate(
            self.coordinator,
            "DELETE",
            f"calendars/samvev/events/{quote(uid, safe='')}",
            {"expectedRevision": self._revision(uid)},
        )
