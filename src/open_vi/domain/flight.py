"""Internal flight command and activity types (not UCI)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Waypoint:
    """Geodetic waypoint for the platform (degrees / meters).

    UCI XML carries lat/lon in radians; the codec converts at the boundary.
    """

    latitude_deg: float
    longitude_deg: float
    altitude_m: float | None = None


@dataclass(frozen=True)
class FlightCommandRequest:
    """Internal command submitted by the Isolator (not UCI)."""

    command_id: UUID
    capability_id: UUID
    command_state: str  # NEW | UPDATE | CANCEL
    mode: str | None  # WAYPOINT_FOLLOWING | HSA_CSA | CURVE_FOLLOWING | None
    waypoints: tuple[Waypoint, ...] = ()
    choice: str = "Capability"  # Capability | Activity
    activity_id: UUID | None = None


@dataclass(frozen=True)
class CommandResult:
    """Accept/reject decision from the platform."""

    # ACCEPTED | REJECTED | CANCELED | RECEIVED | COMPLETED
    processing_state: str
    activity_id: UUID | None = None
    new_activity: bool = True
    reason: str | None = None
    reason_description: str | None = None


@dataclass(frozen=True)
class FlightActivitySnapshot:
    """Active flight activity reported toward MA_FlightActivity."""

    activity_id: UUID
    capability_id: UUID
    activity_state: str = "ACTIVE_UNCONSTRAINED"
    interactive: bool = True


def is_live_activity(activity: FlightActivitySnapshot | None) -> bool:
    """True when a command may UPDATE this activity (not idle or COMPLETED)."""
    return activity is not None and activity.activity_state != "COMPLETED"
