"""Builders for MA_SystemNotification (route ingest, failsafe, etc.)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4
from xml.etree import ElementTree as ET

from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.status import service_id_element
from open_vi.codec.xmlutil import (
    el,
    find_one,
    find_text,
    id_type,
    local_name,
    message_envelope,
    parse_xml,
    system_id,
    tostring,
    utc_now,
    uuid_under,
)
from open_vi.domain import ServiceStatusSnapshot
from open_vi.identity import SystemIdentity


@dataclass(frozen=True)
class InboundResponse:
    """Parsed inbound MA_Response (ids + optional ActivatePlan)."""

    response_id: UUID
    object_state: str | None = None
    route_plan_id: UUID | None = None
    mission_plan_id: UUID | None = None


def parse_response_id(xml: str | bytes) -> UUID | None:
    """Extract ResponseID/UUID from MA_Response."""
    root = parse_xml(xml)
    return uuid_under(root, "ResponseID")


def parse_ma_response(xml: str | bytes) -> InboundResponse | None:
    """Extract ResponseID and optional ActivatePlan route ids.

    ``None`` when MessageData or ResponseID is missing. The first
    ``ActivatePlan`` under MessageData supplies MissionPlanID and
    the first nested RoutePlan/RoutePlanID.
    """
    root = parse_xml(xml)
    if local_name(root) != "MA_Response":
        raise ValueError(f"expected MA_Response, got {local_name(root)}")
    data = find_one(root, "MessageData")
    if data is None:
        return None
    response_id = uuid_under(data, "ResponseID")
    if response_id is None:
        return None
    route_plan_id = None
    mission_plan_id = None
    for node in data.iter():
        if local_name(node) != "ActivatePlan":
            continue
        mission_plan_id = uuid_under(node, "MissionPlanID")
        for child in node.iter():
            if local_name(child) != "RoutePlan":
                continue
            route_plan_id = uuid_under(child, "RoutePlanID")
            if route_plan_id is not None:
                break
        break
    return InboundResponse(
        response_id=response_id,
        object_state=find_text(root, "ObjectState"),
        route_plan_id=route_plan_id,
        mission_plan_id=mission_plan_id,
    )


def build_system_notification(
    identity: SystemIdentity,
    *,
    associated_message_type: str,
    associated_id: UUID | None,
    service: ServiceStatusSnapshot,
    notification_state: str = "CONFIRMED",
    severity: str = "INFORMATIONAL",
    perspective: str = "SOURCE",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build MA_SystemNotification with an AssociatedMessage."""
    source_children: list[ET.Element] = [
        system_id(identity),
        service_id_element(service),
    ]
    associated = el(
        "AssociatedMessage",
        el("MessageType", text=associated_message_type),
    )
    if associated_id is not None:
        associated.append(id_type("AssociatedID", associated_id))
    data = el(
        "MessageData",
        id_type("NotificationID", uuid4()),
        el("NotificationState", text=notification_state),
        el("Timestamp", text=utc_now()),
        el("Source", *source_children),
        el("Severity", text=severity),
        el("SystemSubjectIDs", system_id(identity)),
        el("SystemPerspective", text=perspective),
        associated,
    )
    root = message_envelope(
        "MA_SystemNotification",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_sample_ma_response(
    identity: SystemIdentity,
    *,
    response_id: UUID,
    route_plan_id: UUID | None = None,
    mission_plan_id: UUID | None = None,
    object_state: str = "NEW",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal MA_Response for failsafe unit tests (not schema-complete).

    Without *route_plan_id* the Option is ``DO_NOTHING``. With it the
    Option is ``PLAN_ACTIVATION`` plus ``ActivatePlan`` /
    ``BySubPlan`` / ``RoutePlan``.
    """
    if route_plan_id is None:
        response_type = "DO_NOTHING"
        option = el(
            "Option",
            el("OptionIndex", text="0"),
            el("ContinueEvaluation", text="false"),
            el("Enabled", text="true"),
        )
    else:
        plan_id = mission_plan_id or route_plan_id
        response_type = "PLAN_ACTIVATION"
        option = el(
            "Option",
            el("OptionIndex", text="0"),
            el("ContinueEvaluation", text="false"),
            el("Enabled", text="true"),
            el("Trigger", id_type("ResponseID", response_id)),
            el(
                "Response",
                el(
                    "ActivatePlan",
                    id_type("MissionPlanID", plan_id),
                    el(
                        "ActivationDetails",
                        el(
                            "BySubPlan",
                            el(
                                "RoutePlan",
                                id_type("RoutePlanID", route_plan_id),
                                el("CommandType", text="ACTIVATE"),
                            ),
                        ),
                    ),
                ),
            ),
        )
    data = el(
        "MessageData",
        id_type("ResponseID", response_id),
        el("ResponseType", text=response_type),
        option,
    )
    root = message_envelope(
        "MA_Response",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
        object_state=object_state,
    )
    return tostring(root)
