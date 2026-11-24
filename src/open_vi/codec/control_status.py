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
    secondary_system_id: UUID | None = None,
    secondary_service_id: UUID | None = None,
    in_mission: bool = False,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Publish ControlStatus after control-mode authorization.

    Isolator is always ``PrimaryController`` (it adjudicates
    ``MA_ControlRequest``). The acquired controller is
    ``SecondaryController`` only when both system and service IDs
    are set — the schema requires both. ``MissionControl`` names
    Isolator as ``ControllerSystemID`` (self-controlling VI) and
    ``InMission`` from live flight, route, or task.
    """
    mission_control = el(
        "MissionControl",
        system_id(identity, "ControllerSystemID"),
        el("InMission", text="true" if in_mission else "false"),
    )
    cap_control_children = [
        id_type("CapabilityID", capability_id, offer.capability_label),
        el(
            "PrimaryController",
            system_id(identity),
            service_id_element(service),
        ),
    ]
    if secondary_system_id is not None and secondary_service_id is not None:
        cap_control_children.append(
            el(
                "SecondaryController",
                id_type("SystemID", secondary_system_id),
                id_type("ServiceID", secondary_service_id),
            )
        )
    for iface in offer.accepted_interfaces:
        cap_control_children.append(el("AcceptedInterface", text=iface))
    data = el(
        "MessageData",
        system_id(identity),
        el(
            "ControlType",
            mission_control,
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


def _idle_plan_execution_status(
    root_tag: str,
    identity: SystemIdentity,
    *,
    source: str = "ACTUAL",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """SystemID + Source only. No invented PlanID."""
    data = el(
        "MessageData",
        system_id(identity),
        el("Source", text=source),
    )
    root = message_envelope(
        root_tag,
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_activity_plan_execution_status(
    identity: SystemIdentity,
    *,
    source: str = "ACTUAL",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Idle ActivityPlanExecutionStatus: SystemID + Source.

    Isolator has no ActivityPlanID, so PlanExecutionStatus is omitted.
    """
    return _idle_plan_execution_status(
        "ActivityPlanExecutionStatus",
        identity,
        source=source,
        schema_version=schema_version,
        mode=mode,
    )


def build_route_activity_plan_execution_status(
    identity: SystemIdentity,
    *,
    source: str = "ACTUAL",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Idle RouteActivityPlanExecutionStatus: SystemID + Source.

    Isolator has no RouteActivityPlanID, so PlanExecutionStatus
    and ActivityStatus are omitted.
    """
    return _idle_plan_execution_status(
        "RouteActivityPlanExecutionStatus",
        identity,
        source=source,
        schema_version=schema_version,
        mode=mode,
    )


def build_task_plan_execution_status(
    identity: SystemIdentity,
    *,
    source: str = "ACTUAL",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Idle TaskPlanExecutionStatus: SystemID + Source.

    Isolator has no TaskPlanID, so PlanExecutionStatus is omitted.
    """
    return _idle_plan_execution_status(
        "TaskPlanExecutionStatus",
        identity,
        source=source,
        schema_version=schema_version,
        mode=mode,
    )


def build_response_plan_execution_status(
    identity: SystemIdentity,
    *,
    snapshot: PlanExecutionSnapshot | None = None,
    source: str = "ACTUAL",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """ResponsePlanExecutionStatus: idle Source, or a live composite.

    When *snapshot* is ``None`` this is SystemID + Source only, which
    is the idle form its three sibling plan-status messages also use.
    A live snapshot adds one ``PlanExecutionStatus``.
    """
    children = [
        system_id(identity),
        el("Source", text=snapshot.source if snapshot is not None else source),
    ]
    if snapshot is not None:
        children.append(_plan_execution_status(snapshot, plan_id_tag="PlanID"))
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
    """RoutePlanExecutionStatus for an activated route.

    Still incomplete against A-GRA: the schema requires
    ``CurrentSegment`` (the path and segment being navigated), which
    needs the vehicle's current segment surfaced through
    ``PlatformPort``. Recorded in ``KNOWN_NON_CONFORMANT``.
    """
    data = el(
        "MessageData",
        system_id(identity),
        el("Source", text=snapshot.source),
        _plan_execution_status(snapshot, plan_id_tag="PlanID"),
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
        system_id(identity),
        el("Source", text=snapshot.source),
        _plan_execution_status(snapshot, plan_id_tag="MissionPlanID"),
    )
    root = message_envelope(
        "MA_MissionPlanExecutionStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


# Domain execution state -> PlanExecutionStateEnum. The domain says
# COMPLETED; the standard's token is COMPLETE. Mapping at the codec
# boundary rather than renaming the domain keeps the internal
# comparison in isolator/publishers.py working, and matches the
# convention that wire conversion belongs here (docs/CODEC.md).
_PLAN_EXECUTION_STATE = {
    "PENDING": "PENDING",
    "EXECUTING": "EXECUTING",
    "COMPLETED": "COMPLETE",
    "FAILED": "FAILED",
    "CANCELED": "CANCELED",
}


def plan_execution_state(domain_state: str) -> str:
    """Wire token for a domain execution state.

    An unmapped state passes through unchanged, so a newly added
    domain state shows up as a schema validation failure in the
    conformance suite rather than being quietly rewritten into a
    valid-looking wrong value.
    """
    return _PLAN_EXECUTION_STATE.get(domain_state, domain_state)


def _plan_execution_status(
    snapshot: PlanExecutionSnapshot, *, plan_id_tag: str
):
    """One ``PlanExecutionStatus`` composite.

    A-GRA carries plan execution as a repeating composite of a plan id
    and a state, not as flat sibling fields. *plan_id_tag* differs by
    message: route and response status carry ``PlanID``, mission
    status carries ``MissionPlanID``.

    ``snapshot.activity_id`` is deliberately dropped — none of these
    three messages has a place for it in the content model, so it was
    information the VI was emitting that the standard does not carry
    here.
    """
    plan_id = snapshot.route_plan_id
    if plan_id_tag == "MissionPlanID" and snapshot.mission_plan_id is not None:
        plan_id = snapshot.mission_plan_id
    return el(
        "PlanExecutionStatus",
        id_type(plan_id_tag, plan_id),
        el(
            "PlanExecutionState",
            text=plan_execution_state(snapshot.execution_state),
        ),
    )
