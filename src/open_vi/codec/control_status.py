"""Builders for ControlStatus and ResponsePlanExecutionStatus."""

from __future__ import annotations

from uuid import UUID

from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.status import service_id_element
from open_vi.codec.xmlutil import (
    el,
    id_type,
    message_envelope,
    system_id,
    tostring,
)
from open_vi.identity import SystemIdentity
from open_vi.platform.port import ControlOffer, ServiceStatusSnapshot


def build_control_status(
    identity: SystemIdentity,
    *,
    capability_id: UUID,
    offer: ControlOffer,
    service: ServiceStatusSnapshot,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Publish ControlStatus after control-mode authorization."""
    cap_control_children = [
        id_type("CapabilityID", capability_id, offer.capability_label),
        el(
            "PrimaryController",
            system_id(identity),
            service_id_element(service),
        ),
    ]
    for iface in offer.accepted_interfaces:
        cap_control_children.append(el("AcceptedInterface", text=iface))
    data = el(
        "MessageData",
        system_id(identity),
        el(
            "ControlType",
            el("CapabilityControl", *cap_control_children),
        ),
    )
    root = message_envelope(
        "ControlStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_response_plan_execution_status(
    identity: SystemIdentity,
    *,
    source: str = "ACTUAL",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Idle ResponsePlanExecutionStatus (Loose receive-execution-status)."""
    data = el(
        "MessageData",
        system_id(identity),
        el("Source", text=source),
    )
    root = message_envelope(
        "ResponsePlanExecutionStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)
