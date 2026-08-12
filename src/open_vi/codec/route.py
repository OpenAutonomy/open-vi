"""Parse/build MA route activation + upload outs."""

from __future__ import annotations

from uuid import UUID

from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.xmlutil import (
    el,
    find_one,
    find_text,
    id_type,
    local_name,
    message_envelope,
    parse_xml,
    security_unclassified,
    system_id,
    tostring,
    utc_now,
    uuid_under,
)
from open_vi.identity import SystemIdentity
from open_vi.platform.port import (
    RouteActivationRequest,
    RouteActivationResult,
    StoredRoutePlan,
)


def parse_route_activation_commands(
    xml: str | bytes,
) -> list[RouteActivationRequest]:
    """Extract BySubPlan/RoutePlan activation commands from a message."""
    root = parse_xml(xml)
    data = find_one(root, "MessageData")
    if data is None:
        raise ValueError("MA_MissionPlanActivationCommand missing MessageData")
    command_id = uuid_under(data, "CommandID")
    if command_id is None:
        raise ValueError("missing CommandID UUID")
    command_state = find_text(data, "CommandState") or "NEW"

    results: list[RouteActivationRequest] = []
    for command_el in data:
        if local_name(command_el) != "Command":
            continue
        mission_plan_id = uuid_under(command_el, "MissionPlanID")
        if mission_plan_id is None:
            continue
        for route_el in command_el.iter():
            if local_name(route_el) != "RoutePlan":
                continue
            route_plan_id = uuid_under(route_el, "RoutePlanID")
            cmd_type = find_text(route_el, "CommandType")
            if route_plan_id is None or not cmd_type:
                continue
            results.append(
                RouteActivationRequest(
                    command_id=command_id,
                    mission_plan_id=mission_plan_id,
                    route_plan_id=route_plan_id,
                    command_type=cmd_type,
                    command_state=command_state,
                )
            )
    return results


def parse_route_plan_id(xml: str | bytes) -> UUID:
    """Return RoutePlanID from an inbound MA_RoutePlan."""
    root = parse_xml(xml)
    data = find_one(root, "MessageData")
    if data is None:
        raise ValueError("MA_RoutePlan missing MessageData")
    plan_id = uuid_under(data, "RoutePlanID")
    if plan_id is None:
        raise ValueError("MA_RoutePlan missing RoutePlanID UUID")
    return plan_id


def build_route_activation_status(
    identity: SystemIdentity,
    *,
    command_id: UUID,
    route_plan_id: UUID,
    result: RouteActivationResult,
    plan_state: str | None = None,
    command_status: str | None = None,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build MA_MissionPlanActivationCommandStatus."""
    processing = result.processing_state
    if command_status is None:
        if processing == "REJECTED":
            command_status = "FAILED"
        elif result.emit_pair and plan_state == result.progress_state:
            command_status = "PROCESSING"
        else:
            command_status = "COMPLETED"
    state = plan_state or result.plan_state
    status = el(
        "ActivationStatus",
        el("CommandProcessingState", text=processing),
        el("CommandStatus", text=command_status),
    )
    by_state = el(
        "ActivationCommandByState",
        el("PlanActivationCommandState", text=state),
        el("Plans", id_type("RoutePlanID", route_plan_id)),
    )
    data = el(
        "MessageData",
        id_type("CommandID", command_id),
        status,
        by_state,
    )
    root = message_envelope(
        "MA_MissionPlanActivationCommandStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_file_metadata_for_route(
    identity: SystemIdentity,
    stored: StoredRoutePlan,
    *,
    file_metadata_id: UUID,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build FileMetadata for a stored MA_RoutePlan copy."""
    data = el(
        "MessageData",
        id_type("FileMetadataID", file_metadata_id),
        el(
            "FileDescription",
            el("FileType", text="OTHER"),
            el(
                "FileFormat",
                el("MIME", text="application/xml"),
            ),
        ),
        el("FileName", text=f"route-{stored.route_plan_id.hex}.xml"),
        el("FileSource", system_id(identity)),
        el("CreationSource", text="PROCESSED"),
        el("UntrustedModification", text="false"),
        el("Timestamp", text=utc_now()),
        security_unclassified(),
        el("SHA_2_Hash", text=stored.sha256_hex),
    )
    root = message_envelope(
        "FileMetadata",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
        object_state="NEW",
    )
    return tostring(root)


def build_file_location_for_route(
    identity: SystemIdentity,
    stored: StoredRoutePlan,
    *,
    file_location_id: UUID,
    file_metadata_id: UUID,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build FileLocation pointing at the retained route plan URI."""
    uri = f"uci://open-vi/routes/{stored.route_plan_id.hex}"
    data = el(
        "MessageData",
        id_type("FileLocationID", file_location_id),
        id_type("FileMetadataID", file_metadata_id),
        el(
            "LocationAndStatus",
            el("Status", text="TEMPORARY"),
            el(
                "Location",
                el("Network", el("Address", text=uri)),
            ),
        ),
    )
    root = message_envelope(
        "FileLocation",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
        object_state="NEW",
    )
    return tostring(root)


def build_sample_route_activation_command(
    identity: SystemIdentity,
    *,
    command_id: UUID,
    mission_plan_id: UUID,
    route_plan_id: UUID,
    command_type: str,
    command_state: str = "NEW",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal BySubPlan/RoutePlan activation command for tests."""
    command = el(
        "Command",
        id_type("MissionPlanID", mission_plan_id),
        el(
            "ActivationDetails",
            el(
                "BySubPlan",
                el(
                    "RoutePlan",
                    id_type("RoutePlanID", route_plan_id),
                    el("CommandType", text=command_type),
                ),
            ),
        ),
    )
    data = el(
        "MessageData",
        id_type("CommandID", command_id),
        el("CommandState", text=command_state),
        command,
    )
    root = message_envelope(
        "MA_MissionPlanActivationCommand",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_sample_route_plan(
    identity: SystemIdentity,
    *,
    route_plan_id: UUID,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal MA_RoutePlan for unit tests (RoutePlanID + placeholder)."""
    data = el(
        "MessageData",
        id_type("RoutePlanID", route_plan_id),
        el("ForPlanningUseOnly", text="false"),
    )
    root = message_envelope(
        "MA_RoutePlan",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
        object_state="NEW",
    )
    return tostring(root)
