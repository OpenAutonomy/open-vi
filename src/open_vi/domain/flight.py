"""Internal flight command and activity types (not UCI)."""

from __future__ import annotations

import math
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
    # MA_ValidationResultEnum values for CannotComplyDetails.
    validation_results: tuple[str, ...] = ()


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


def validate_waypoint_path(
    waypoints: tuple[Waypoint, ...],
    *,
    min_rel_alt_m: float,
    max_rel_alt_m: float,
    home_hae_m: float | None,
) -> CommandResult | None:
    """Reject an unflyable waypoint path, or return ``None`` if it is ok.

    Altitudes are compared relative to home. When *home_hae_m* is set,
    each waypoint HAE minus home is the AGL used against the envelope.
    When home is unknown, *altitude_m* is treated as already relative.
    """
    if not waypoints:
        return CommandResult(
            processing_state="REJECTED",
            reason="INVALID_INPUT_PARAMETER",
            reason_description="WAYPOINT_FOLLOWING requires waypoints",
            validation_results=("INVALID_WAYPOINT",),
        )
    for index, waypoint in enumerate(waypoints):
        if not _finite_lat_lon(waypoint):
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description=(
                    f"Waypoint {index} has a non-finite lat/lon"
                ),
                validation_results=("INVALID_WAYPOINT",),
            )
        if waypoint.altitude_m is None or not math.isfinite(
            waypoint.altitude_m
        ):
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description=(
                    f"Waypoint {index} is missing a finite altitude"
                ),
                validation_results=("INVALID_WAYPOINT",),
            )
        if home_hae_m is None:
            rel_m = float(waypoint.altitude_m)
        else:
            rel_m = float(waypoint.altitude_m) - home_hae_m
        if rel_m < min_rel_alt_m or rel_m > max_rel_alt_m:
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description=(
                    f"Waypoint {index} relative alt {rel_m:.1f}m "
                    f"outside [{min_rel_alt_m:.1f}, {max_rel_alt_m:.1f}]"
                ),
                validation_results=("PERFORMANCE_LIMIT_EXCEEDED",),
            )
    return None


def _finite_lat_lon(waypoint: Waypoint) -> bool:
    """True when lat and lon are finite numbers."""
    return math.isfinite(waypoint.latitude_deg) and math.isfinite(
        waypoint.longitude_deg
    )
