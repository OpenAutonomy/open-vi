"""Builders for ControlStatus and plan-execution status outs."""

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
from open_vi.domain import (
    ControlOffer,
    PlanExecutionSnapshot,
    ServiceStatusSnapshot,
)
from open_vi.identity import SystemIdentity


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
    snapshot: PlanExecutionSnapshot | None = None,
    source: str = "ACTUAL",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """ResponsePlanExecutionStatus: idle Source, or live plan ids.

    When *snapshot* is ``None`` this is SystemID + Source only.
    A live snapshot adds ExecutionState, RoutePlanID, and optional
    MissionPlanID / ActivityID.
    """
    children = [
        system_id(identity),
        el("Source", text=snapshot.source if snapshot is not None else source),
    ]
    if snapshot is not None:
        children.extend(_execution_ids(snapshot))
    data = el("MessageData", *children)
    root = message_envelope(
        "ResponsePlanExecutionStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_route_plan_execution_status(
    identity: SystemIdentity,
    snapshot: PlanExecutionSnapshot,
    *,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """RoutePlanExecutionStatus for an activated route."""
    data = el(
        "MessageData",
        system_id(identity, "ExecutingSystemID"),
        *_execution_ids(snapshot),
    )
    root = message_envelope(
        "RoutePlanExecutionStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_mission_plan_execution_status(
    identity: SystemIdentity,
    snapshot: PlanExecutionSnapshot,
    *,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """MA_MissionPlanExecutionStatus when MissionPlanID is known."""
    data = el(
        "MessageData",
        system_id(identity, "ExecutingSystemID"),
        *_execution_ids(snapshot),
    )
    root = message_envelope(
        "MA_MissionPlanExecutionStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def _execution_ids(snapshot: PlanExecutionSnapshot) -> list:
    """ExecutionState plus Route / Mission / Activity ids."""
    children = [
        el("ExecutionState", text=snapshot.execution_state),
        id_type("RoutePlanID", snapshot.route_plan_id),
    ]
    if snapshot.mission_plan_id is not None:
        children.append(id_type("MissionPlanID", snapshot.mission_plan_id))
    if snapshot.activity_id is not None:
        children.append(
            id_type("ActivityID", snapshot.activity_id, "flight-activity")
        )
    return children
