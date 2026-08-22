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
from open_vi.domain import ControlOffer, ControlReadiness, FlightModeProfile
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
