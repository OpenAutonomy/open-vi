"""Builders for MA_FlightCapability and MA_FlightCapabilityStatus."""

from __future__ import annotations

from uuid import UUID

from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.xmlutil import el, id_type, message_envelope, tostring
from open_vi.identity import SystemIdentity
from open_vi.platform.port import ControlOffer, ControlReadiness


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
