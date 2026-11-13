"""Runtime data container for one Samvev config entry."""

from dataclasses import dataclass

from .api import SamvevClient
from .coordinator import SamvevDataUpdateCoordinator


@dataclass(slots=True)
class SamvevRuntimeData:
    """Runtime objects owned by a loaded config entry."""

    client: SamvevClient
    coordinator: SamvevDataUpdateCoordinator
