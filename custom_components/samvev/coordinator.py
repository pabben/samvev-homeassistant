"""Authoritative snapshot polling and durable, idempotent HA mutations."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from typing import TYPE_CHECKING, Any
from uuid import uuid4

from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import (
    SamvevApiError,
    SamvevAuthenticationError,
    SamvevClient,
    SamvevConflictError,
    SamvevConnectionError,
    SamvevInvalidResponseError,
    SamvevRequestError,
)
from .const import DEFAULT_SCAN_INTERVAL, DOMAIN

if TYPE_CHECKING:
    from datetime import datetime

    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)
MAX_PENDING_OPERATIONS = 128


class SamvevDataUpdateCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Poll shared content; keep retry keys, never a second content database."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        client: SamvevClient,
        connection: dict[str, Any] | None = None,
    ) -> None:
        """Initialize coordination and a secret-free operation-key store."""
        super().__init__(
            hass,
            logger=_LOGGER,
            config_entry=config_entry,
            name=DOMAIN,
            update_interval=DEFAULT_SCAN_INTERVAL,
            always_update=True,
        )
        self.client = client
        self.connection = connection or {}
        self.last_success: datetime | None = None
        self.authorization_revoked = False
        self.data = {}
        self._expected_identity = (
            (connection["installationId"], connection["connectionId"])
            if connection
            else None
        )
        self._store: Store[dict[str, Any]] = Store(
            hass, 1, f"{DOMAIN}.{config_entry.entry_id}.operations"
        )
        self._operations: dict[str, dict[str, Any]] | None = None
        self._write_lock = asyncio.Lock()

    async def _async_update_data(self) -> dict[str, Any]:
        """Retain stale content on transport errors, clear it on revoked access."""
        try:
            snapshot = await self.client.async_snapshot()
            identity = (snapshot["installationId"], snapshot["connectionId"])
            if self._expected_identity and identity != self._expected_identity:
                raise SamvevAuthenticationError("Samvev connection identity changed")  # noqa: TRY301
        except SamvevAuthenticationError:
            self.authorization_revoked = True
            self.data = {}
            self.async_update_listeners()
            raise ConfigEntryAuthFailed("Samvev authorization rejected") from None
        except SamvevApiError:
            raise UpdateFailed("Unable to refresh the Samvev snapshot") from None
        self.authorization_revoked = False
        self.connection = {
            key: value
            for key, value in snapshot.items()
            if key not in {"lists", "messages", "calendars", "serverNow"}
        }
        self.last_success = dt_util.utcnow()
        return snapshot

    async def async_mutate(
        self,
        method: str,
        endpoint: str,
        payload: dict[str, Any],
        request_key: str | None = None,
    ) -> dict[str, Any]:
        """Confirm with Samvev before refreshing; preserve ambiguous retries."""
        async with self._write_lock:
            if self.authorization_revoked:
                raise SamvevAuthenticationError("Samvev authorization rejected")
            body = dict(payload)
            supplied_key = request_key or body.pop("requestKey", None)
            fingerprint = hashlib.sha256(
                json.dumps(
                    [method, endpoint, body, supplied_key],
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            if self._operations is None:
                saved = await self._store.async_load()
                self._operations = saved.get("operations", {}) if saved else {}
            now = time.time()
            self._operations = {
                key: value
                for key, value in self._operations.items()
                if value.get("completedUntil") is None or value["completedUntil"] > now
            }
            operation = self._operations.get(fingerprint)
            if operation is None:
                if len(self._operations) >= MAX_PENDING_OPERATIONS:
                    raise SamvevRequestError(
                        "Resolve pending Samvev operations before creating more"
                    )
                operation = {
                    "requestKey": supplied_key or str(uuid4()),
                    "completedUntil": None,
                }
                self._operations[fingerprint] = operation
                await self._save_operations()
            body["requestKey"] = operation["requestKey"]
            try:
                result = await self.client.async_mutate(method, endpoint, body)
            except (SamvevConnectionError, SamvevInvalidResponseError):
                # A request can commit before its response is lost. Keep the key.
                raise
            except (SamvevConflictError, SamvevRequestError, SamvevAuthenticationError):
                self._operations.pop(fingerprint, None)
                await self._save_operations()
                await self.async_refresh()
                raise
            operation["completedUntil"] = time.time() + 10
            await self._save_operations()
            await self.async_refresh()
            return result

    async def _save_operations(self) -> None:
        """Persist only hashes and retry metadata, without content or tokens."""
        await self._store.async_save({"operations": self._operations})

    async def async_remove_operations(self) -> None:
        """Remove local retry metadata when the config entry is deleted."""
        await self._store.async_remove()
