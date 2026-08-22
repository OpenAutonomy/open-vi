"""Build and parse MA_FlightCapability and status."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.xmlutil import (
    el,
    find_all,
    find_one,
    find_text,
    id_type,
    message_envelope,
    parse_xml,
    tostring,
    uuid_under,
)
from open_vi.domain import (
    AccelerationLimit,
    AirspeedLimit,
    ControlOffer,
    ControlReadiness,
    FlightModeProfile,
)
from open_vi.identity import SystemIdentity


@dataclass(frozen=True)
class FlightCapabilityDesignation:
    """Parsed inbound MA_FlightCapability modes (C2 designation)."""

    capability_types: tuple[str, ...]
    capability_id: UUID | None = None
    object_state: str | None = None


def parse_flight_capability(
    xml: str | bytes,
) -> FlightCapabilityDesignation:
    """Extract CapabilityType tokens and optional CapabilityID."""
    root = parse_xml(xml)
    data = find_one(root, "MessageData")
    types: list[str] = []
    capability_id = None
    if data is not None:
        capability_id = uuid_under(data, "CapabilityID")
        for node in find_all(data, "CapabilityType"):
            raw = (node.text or "").strip().upper().replace("-", "_")
            if raw and raw not in types:
                types.append(raw)
    return FlightCapabilityDesignation(
        capability_types=tuple(types),
        capability_id=capability_id,
        object_state=find_text(root, "ObjectState"),
    )


def build_flight_capability(
    identity: SystemIdentity,
    offer: ControlOffer,
    *,
    capability_id: UUID,
    object_state: str = "NEW",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Advertise flight control modes (control-mode authorization step 1)."""
    capability_children = [
        id_type("CapabilityID", capability_id, offer.capability_label),
    ]
    for iface in offer.accepted_interfaces:
        capability_children.append(el("AcceptedInterface", text=iface))
    for cap_type in offer.capability_types:
        capability_children.append(el("CapabilityType", text=cap_type))
    profile_el = _performance_profile_block(offer)
    if profile_el is not None:
        capability_children.append(profile_el)

    data = el(
        "MessageData",
        el("Capability", *capability_children),
    )
    root = message_envelope(
        "MA_FlightCapability",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
        object_state=object_state,
    )
    return tostring(root)


def _performance_profile_block(offer: ControlOffer):
    """HSA, waypoint, and curve envelopes, or None when all are unset."""
    kids = []
    hsa = _mode_limits(offer.hsa_profile)
    if hsa is not None:
        kids.append(el("HSA_CSA_PerformanceProfile", *hsa))
    waypoint = _mode_limits(offer.waypoint_profile)
    if waypoint is not None:
        kids.append(el("WaypointFollowingPerformanceProfile", *waypoint))
    curve = _mode_limits(offer.curve_profile)
    if curve is not None:
        kids.append(el("CurveFollowingPerformanceProfile", *curve))
    if not kids:
        return None
    return el("FlightCapabilityPerformanceProfile", *kids)


def _mode_limits(profile: FlightModeProfile | None):
    """UCI mode-profile children in schema order, or None when empty."""
    if profile is None:
        return None
    kids = []
    kids.extend(
        _airspeed_limit("MinAirspeed", sample)
        for sample in profile.min_airspeed
    )
    kids.extend(
        _airspeed_limit("MaxAirspeed", sample)
        for sample in profile.max_airspeed
    )
    kids.extend(
        _airspeed_limit("BestEnduranceAirspeed", sample)
        for sample in profile.best_endurance_airspeed
    )
    kids.extend(
        _airspeed_limit("BestRangeAirspeed", sample)
        for sample in profile.best_range_airspeed
    )
    if profile.min_altitude_m is not None:
        kids.append(
            _altitude_limit(
                "MinAltitude",
                profile.min_altitude_m,
                profile.altitude_ref,
            )
        )
    if profile.max_altitude_m is not None:
        kids.append(
            _altitude_limit(
                "MaxAltitude",
                profile.max_altitude_m,
                profile.altitude_ref,
            )
        )
    kids.extend(
        _acceleration_limit("MinAccelerationLimits", sample)
        for sample in profile.min_acceleration
    )
    kids.extend(
        _acceleration_limit("MaxAccelerationLimits", sample)
        for sample in profile.max_acceleration
    )
    if profile.max_turn_rate_rps is not None:
        kids.append(el("MaxTurnRate", text=_qty(profile.max_turn_rate_rps)))
    if profile.max_climb_rate_mps is not None:
        kids.append(el("MaxClimbRate", text=_qty(profile.max_climb_rate_mps)))
    if profile.max_descent_rate_mps is not None:
        kids.append(
            el("MaxDescentRate", text=_qty(profile.max_descent_rate_mps))
        )
    return kids or None


def _airspeed_limit(tag: str, sample: AirspeedLimit):
    """Min/Max/Best*Airspeed with altitude (optional weight)."""
    kids = [
        el(
            "AirspeedLimit",
            el("Value", text=_qty(sample.speed_mps)),
            el("Reference", text=sample.speed_ref),
        ),
        el(
            "AltitudePair",
            el("AltitudeReference", text=sample.altitude_ref),
            el("Altitude", text=_qty(sample.altitude_m)),
        ),
    ]
    if sample.weight_kg is not None:
        kids.append(el("WeightPair", text=_qty(sample.weight_kg)))
    return el(tag, *kids)


def _acceleration_limit(tag: str, sample: AccelerationLimit):
    """Min/MaxAccelerationLimits with the required pair choice."""
    if sample.mach is not None:
        pair = el(
            "AccelerationLimitPair",
            el("MachValue", text=_qty(sample.mach)),
        )
    else:
        pair = el(
            "AccelerationLimitPair",
            el(
                "BodyReferenceOrientationRate",
                el("RollRate", text=_qty(sample.roll_rate_rps or 0.0)),
                el("PitchRate", text=_qty(sample.pitch_rate_rps or 0.0)),
                el("YawRate", text=_qty(sample.yaw_rate_rps or 0.0)),
            ),
        )
    return el(
        tag,
        el(
            "AccelerationLimit",
            el("X_Accel", text=_qty(sample.x_mps2)),
            el("Y_Accel", text=_qty(sample.y_mps2)),
            el("Z_Accel", text=_qty(sample.z_mps2)),
        ),
        pair,
    )


def _altitude_limit(tag: str, altitude_m: float, altitude_ref: str):
    """MinAltitude / MaxAltitude with AltitudeReferenceType children."""
    return el(
        tag,
        el("AltitudeReference", text=altitude_ref),
        el("Altitude", text=_qty(altitude_m)),
    )


def _qty(value: float) -> str:
    """Serialize a UCI double quantity."""
    return f"{value:.3f}"


def build_flight_capability_status(
    identity: SystemIdentity,
    readiness: ControlReadiness,
    *,
    capability_id: UUID,
    capability_label: str = "flight-capability",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Publish readiness so MA may begin issuing FlightCommands."""
    availability_children = [el("Availability", text=readiness.availability)]
    if readiness.reason:
        availability_children.append(
            el(
                "AvailabilityReason",
                el("Reason", text=readiness.reason),
            )
        )
    status = el(
        "CapabilityStatus",
        id_type("CapabilityID", capability_id, capability_label),
        el("AvailabilityInfo", *availability_children),
    )
    data = el("MessageData", status)
    root = message_envelope(
        "MA_FlightCapabilityStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)
