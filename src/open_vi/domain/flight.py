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
class HsaCsaSetpoint:
    """Heading / speed / altitude hold. Degrees and meters.

    Omitted axes mean hold current. ``unsupported`` is a parse-time
    flag (``MACH``, ``SPEED_OPTIMIZATION``) so the platform can
    reject without inventing a conversion.
    """

    altitude_m: float | None = None
    # WGS_HAE | AGL | MSL | ALTITUDE_BAROMETRIC
    altitude_ref: str | None = None
    speed_mps: float | None = None
    # GROUNDSPEED | TRUE_AIRSPEED | CALIBRATED_AIRSPEED
    speed_ref: str | None = None
    heading_deg: float | None = None
    direction_kind: str | None = None  # HEADING | COURSE
    heading_ref: str | None = None  # TRUE_NORTH | MAGNETIC_NORTH
    unsupported: str | None = None


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
    hsa: HsaCsaSetpoint | None = None


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


def finite_waypoint_geometry(waypoints: tuple[Waypoint, ...]) -> bool:
    """True when the path is non-empty and every point is finite.

    Isolator route validation uses this. Envelope limits stay on the
    platform (PX4 :func:`validate_waypoint_path`).
    """
    if not waypoints:
        return False
    for waypoint in waypoints:
        if not _finite_lat_lon(waypoint):
            return False
        if waypoint.altitude_m is None or not math.isfinite(
            waypoint.altitude_m
        ):
            return False
    return True


# Operator Hold and capability XML use 0.1 m. Compare on that grid so
# an advertised bound (home + limit, three decimals) is flyable after
# the UI rounds it.
_ENVELOPE_DIGITS = 1


def _quantize_m(value: float, digits: int = _ENVELOPE_DIGITS) -> float:
    """Round metres to *digits* so wire and UI share one bound."""
    scale = 10**digits
    return round(value * scale) / scale


def _outside_rel_envelope(
    rel_m: float, min_rel_m: float, max_rel_m: float
) -> bool:
    """True when *rel_m* is outside ``[min, max]`` on the 0.1 m grid."""
    rel = _quantize_m(rel_m)
    return rel < _quantize_m(min_rel_m) or rel > _quantize_m(max_rel_m)


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
        if _outside_rel_envelope(rel_m, min_rel_alt_m, max_rel_alt_m):
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


_HSA_ALT_REFS = frozenset({"AGL", "WGS_HAE"})
_HSA_SPEED_REFS = frozenset({"GROUNDSPEED"})
_HSA_HEADING_REFS = frozenset({"TRUE_NORTH"})


def validate_hsa_setpoint(
    hsa: HsaCsaSetpoint | None,
    *,
    min_rel_alt_m: float,
    max_rel_alt_m: float,
    home_hae_m: float | None,
) -> CommandResult | None:
    """Reject an unflyable HSA vector, or return ``None`` if it is ok.

    Empty (all axes omitted) is a hold-current enter. Envelope applies
    only when altitude is commanded. HAE minus home is the AGL used
    against the envelope, same as :func:`validate_waypoint_path`.
    """
    if hsa is None:
        return None
    if hsa.unsupported:
        return CommandResult(
            processing_state="REJECTED",
            reason="CAPABILITY_UNAVAILABLE",
            reason_description=(f"HSA_CSA does not accept {hsa.unsupported}"),
            validation_results=("CAPABILITY_NOT_SUPPORTED",),
        )
    if hsa.altitude_ref is not None and hsa.altitude_ref not in _HSA_ALT_REFS:
        return CommandResult(
            processing_state="REJECTED",
            reason="CAPABILITY_UNAVAILABLE",
            reason_description=(
                f"HSA altitude reference {hsa.altitude_ref} is not supported"
            ),
            validation_results=("CAPABILITY_NOT_SUPPORTED",),
        )
    if hsa.speed_ref is not None and hsa.speed_ref not in _HSA_SPEED_REFS:
        return CommandResult(
            processing_state="REJECTED",
            reason="CAPABILITY_UNAVAILABLE",
            reason_description=(
                f"HSA speed reference {hsa.speed_ref} is not supported"
            ),
            validation_results=("CAPABILITY_NOT_SUPPORTED",),
        )
    if hsa.heading_ref is not None and hsa.heading_ref not in _HSA_HEADING_REFS:
        return CommandResult(
            processing_state="REJECTED",
            reason="CAPABILITY_UNAVAILABLE",
            reason_description=(
                f"HSA heading reference {hsa.heading_ref} is not supported"
            ),
            validation_results=("CAPABILITY_NOT_SUPPORTED",),
        )
    if hsa.speed_mps is not None and (
        not math.isfinite(hsa.speed_mps) or hsa.speed_mps < 0.0
    ):
        return CommandResult(
            processing_state="REJECTED",
            reason="INVALID_INPUT_PARAMETER",
            reason_description="HSA speed must be a finite non-negative m/s",
            validation_results=("INVALID_WAYPOINT",),
        )
    if hsa.heading_deg is not None and not math.isfinite(hsa.heading_deg):
        return CommandResult(
            processing_state="REJECTED",
            reason="INVALID_INPUT_PARAMETER",
            reason_description="HSA heading must be finite",
            validation_results=("INVALID_WAYPOINT",),
        )
    if hsa.altitude_m is None:
        return None
    if not math.isfinite(hsa.altitude_m):
        return CommandResult(
            processing_state="REJECTED",
            reason="INVALID_INPUT_PARAMETER",
            reason_description="HSA altitude must be finite",
            validation_results=("INVALID_WAYPOINT",),
        )
    if hsa.altitude_ref == "WGS_HAE" and home_hae_m is not None:
        rel_m = float(hsa.altitude_m) - home_hae_m
        lo_hae = home_hae_m + min_rel_alt_m
        hi_hae = home_hae_m + max_rel_alt_m
        description = (
            f"HSA altitude {hsa.altitude_m:.1f}m HAE "
            f"outside [{lo_hae:.1f}, {hi_hae:.1f}]"
        )
    else:
        rel_m = float(hsa.altitude_m)
        description = (
            f"HSA relative alt {rel_m:.1f}m "
            f"outside [{min_rel_alt_m:.1f}, {max_rel_alt_m:.1f}]"
        )
    if _outside_rel_envelope(rel_m, min_rel_alt_m, max_rel_alt_m):
        return CommandResult(
            processing_state="REJECTED",
            reason="INVALID_INPUT_PARAMETER",
            reason_description=description,
            validation_results=("PERFORMANCE_LIMIT_EXCEEDED",),
        )
    return None


def _finite_lat_lon(waypoint: Waypoint) -> bool:
    """True when lat and lon are finite numbers."""
    return math.isfinite(waypoint.latitude_deg) and math.isfinite(
        waypoint.longitude_deg
    )
