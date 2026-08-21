"""Builders for MA_FlightCapability and MA_FlightCapabilityStatus."""

from __future__ import annotations

from uuid import UUID

from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.xmlutil import el, id_type, message_envelope, tostring
from open_vi.domain import ControlOffer, ControlReadiness, FlightModeProfile
from open_vi.identity import SystemIdentity


def build_flight_capability(
    identity: SystemIdentity,
    offer: ControlOffer,
    *,
    capability_id: UUID,
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
        object_state="NEW",
    )
    return tostring(root)


def _performance_profile_block(offer: ControlOffer):
    """HSA and waypoint min/max, or None when both are unset."""
    kids = []
    hsa = _mode_limits(offer.hsa_profile)
    if hsa is not None:
        kids.append(el("HSA_CSA_PerformanceProfile", *hsa))
    waypoint = _mode_limits(offer.waypoint_profile)
    if waypoint is not None:
        kids.append(el("WaypointFollowingPerformanceProfile", *waypoint))
    if not kids:
        return None
    return el("FlightCapabilityPerformanceProfile", *kids)


def _mode_limits(profile: FlightModeProfile | None):
    """MinAltitude / MaxAltitude children, or None when unset."""
    if profile is None:
        return None
    kids = []
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
    return kids or None


def _altitude_limit(tag: str, altitude_m: float, altitude_ref: str):
    """MinAltitude / MaxAltitude with AltitudeReferenceType children."""
    return el(
        tag,
        el("AltitudeReference", text=altitude_ref),
        el("Altitude", text=f"{altitude_m:.3f}"),
    )


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
