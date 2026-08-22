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
class CurveControlPoint:
    """AEP offset (east / north metres) and NURBS weight."""

    east_m: float
    north_m: float
    weight: float = 1.0


@dataclass(frozen=True)
class CurveFollowingSetpoint:
    """NURBS spine in AEP metres from a geodetic center."""

    center_lat_deg: float
    center_lon_deg: float
    center_alt_m: float | None = None
    control_points: tuple[CurveControlPoint, ...] = ()
    knots: tuple[float, ...] = ()


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
    curve: CurveFollowingSetpoint | None = None


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


_EARTH_RADIUS_M = 6378137.0
_MIN_CURVE_CONTROL_POINTS = 4


def aep_offset_to_geodetic(
    lat_deg: float,
    lon_deg: float,
    east_m: float,
    north_m: float,
) -> tuple[float, float]:
    """Azimuthal-equidistant east/north metres → geodetic degrees."""
    dlat = math.degrees(north_m / _EARTH_RADIUS_M)
    cos_lat = math.cos(math.radians(lat_deg))
    if abs(cos_lat) < 1e-12:
        dlon = 0.0
    else:
        dlon = math.degrees(east_m / (_EARTH_RADIUS_M * cos_lat))
    return lat_deg + dlat, lon_deg + dlon


def sample_curve_waypoints(
    curve: CurveFollowingSetpoint,
    *,
    altitude_m: float,
    samples: int = 16,
) -> tuple[Waypoint, ...]:
    """Sample the NURBS (or control-point polyline) as geodetic waypoints.

    When the knot vector does not yield a degree ≥ 1, the control
    points are flown as a polyline. *altitude_m* is HAE on every
    sample — the XML spine is 2-D AEP.
    """
    offsets = _sample_aep_offsets(curve, samples)
    waypoints: list[Waypoint] = []
    for east_m, north_m in offsets:
        lat, lon = aep_offset_to_geodetic(
            curve.center_lat_deg, curve.center_lon_deg, east_m, north_m
        )
        waypoints.append(Waypoint(lat, lon, altitude_m))
    return tuple(waypoints)


def validate_curve_following(
    curve: CurveFollowingSetpoint | None,
    *,
    altitude_m: float,
    min_rel_alt_m: float,
    max_rel_alt_m: float,
    home_hae_m: float | None,
) -> CommandResult | None:
    """Reject an unflyable curve, or return ``None`` if it is ok.

    Schema minimum is four control points. Sampled HAE uses the
    waypoint envelope.
    """
    if curve is None:
        return CommandResult(
            processing_state="REJECTED",
            reason="INVALID_INPUT_PARAMETER",
            reason_description="CURVE_FOLLOWING requires CurveSegments",
            validation_results=("INVALID_WAYPOINT",),
        )
    if not _finite_lat_lon(
        Waypoint(curve.center_lat_deg, curve.center_lon_deg)
    ):
        return CommandResult(
            processing_state="REJECTED",
            reason="INVALID_INPUT_PARAMETER",
            reason_description="Curve CenterReference is non-finite",
            validation_results=("INVALID_WAYPOINT",),
        )
    if len(curve.control_points) < _MIN_CURVE_CONTROL_POINTS:
        return CommandResult(
            processing_state="REJECTED",
            reason="INVALID_INPUT_PARAMETER",
            reason_description=(
                "CURVE_FOLLOWING requires at least four control points"
            ),
            validation_results=("INVALID_WAYPOINT",),
        )
    for index, point in enumerate(curve.control_points):
        if not (
            math.isfinite(point.east_m)
            and math.isfinite(point.north_m)
            and math.isfinite(point.weight)
            and point.weight > 0.0
        ):
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description=(
                    f"Control point {index} is non-finite or weight ≤ 0"
                ),
                validation_results=("INVALID_WAYPOINT",),
            )
    if any(not math.isfinite(knot) for knot in curve.knots):
        return CommandResult(
            processing_state="REJECTED",
            reason="INVALID_INPUT_PARAMETER",
            reason_description="Curve KnotVector is non-finite",
            validation_results=("INVALID_WAYPOINT",),
        )
    if not math.isfinite(altitude_m):
        return CommandResult(
            processing_state="REJECTED",
            reason="INVALID_INPUT_PARAMETER",
            reason_description="Curve sample altitude must be finite",
            validation_results=("INVALID_WAYPOINT",),
        )
    return validate_waypoint_path(
        sample_curve_waypoints(curve, altitude_m=altitude_m),
        min_rel_alt_m=min_rel_alt_m,
        max_rel_alt_m=max_rel_alt_m,
        home_hae_m=home_hae_m,
    )


def _nurbs_degree(n_points: int, n_knots: int) -> int | None:
    """p = m − n − 1, or ``None`` when the knot vector is not usable."""
    degree = n_knots - n_points - 1
    if degree < 1:
        return None
    return degree


def _sample_aep_offsets(
    curve: CurveFollowingSetpoint, samples: int
) -> list[tuple[float, float]]:
    """AEP (east, north) samples, or the control-point polyline."""
    points = curve.control_points
    knots = curve.knots
    degree = _nurbs_degree(len(points), len(knots))
    if degree is None or not _knots_non_decreasing(knots):
        return [(point.east_m, point.north_m) for point in points]
    return _evaluate_nurbs(points, knots, degree, samples)


def _knots_non_decreasing(knots: tuple[float, ...]) -> bool:
    return all(
        knots[index] <= knots[index + 1] for index in range(len(knots) - 1)
    )


def _evaluate_nurbs(
    points: tuple[CurveControlPoint, ...],
    knots: tuple[float, ...],
    degree: int,
    samples: int,
) -> list[tuple[float, float]]:
    """Evaluate a 2-D NURBS at *samples* parameters in the valid span."""
    n_points = len(points)
    u_start = knots[degree]
    u_end = knots[n_points]
    if u_end <= u_start:
        return [(point.east_m, point.north_m) for point in points]
    count = max(samples, n_points)
    offsets: list[tuple[float, float]] = []
    for index in range(count):
        if count == 1:
            param = u_start
        else:
            param = u_start + (u_end - u_start) * index / (count - 1)
        if index == count - 1:
            param = u_end - 1e-12
        offsets.append(_nurbs_point(points, knots, degree, param))
    return offsets


def _nurbs_point(
    points: tuple[CurveControlPoint, ...],
    knots: tuple[float, ...],
    degree: int,
    param: float,
) -> tuple[float, float]:
    """Weighted Cox-de Boor evaluation at *param*."""
    east = 0.0
    north = 0.0
    weight_sum = 0.0
    for index, point in enumerate(points):
        basis = _cox_de_boor(knots, index, degree, param) * point.weight
        east += point.east_m * basis
        north += point.north_m * basis
        weight_sum += basis
    if weight_sum <= 0.0:
        return points[0].east_m, points[0].north_m
    return east / weight_sum, north / weight_sum


def _cox_de_boor(
    knots: tuple[float, ...], index: int, degree: int, param: float
) -> float:
    """N_{index,degree}(*param*)."""
    if degree == 0:
        upper = knots[index + 1] if index + 1 < len(knots) else knots[index]
        if knots[index] <= param < upper:
            return 1.0
        return 0.0
    left = 0.0
    denom_left = knots[index + degree] - knots[index]
    if denom_left != 0.0:
        left = (
            (param - knots[index])
            / denom_left
            * _cox_de_boor(knots, index, degree - 1, param)
        )
    right = 0.0
    if index + degree + 1 < len(knots):
        denom_right = knots[index + degree + 1] - knots[index + 1]
        if denom_right != 0.0:
            right = (
                (knots[index + degree + 1] - param)
                / denom_right
                * _cox_de_boor(knots, index + 1, degree - 1, param)
            )
    return left + right


def _finite_lat_lon(waypoint: Waypoint) -> bool:
    """True when lat and lon are finite numbers."""
    return math.isfinite(waypoint.latitude_deg) and math.isfinite(
        waypoint.longitude_deg
    )
