"""Parse/build MA route activation + upload outs."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID
from xml.etree import ElementTree as ET

from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.path import build_path_element, parse_path_waypoints
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
from open_vi.domain import (
    RouteActivationRequest,
    RouteActivationResult,
    StoredRoutePlan,
    Waypoint,
)
from open_vi.identity import SystemIdentity


def parse_route_activation_commands(
    xml: str | bytes,
) -> list[RouteActivationRequest]:
    """Extract BySubPlan/RoutePlan or ByMissionPlan activation commands."""
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
        found_route = False
        for route_el in command_el.iter():
            if local_name(route_el) != "RoutePlan":
                continue
            route_plan_id = uuid_under(route_el, "RoutePlanID")
            cmd_type = find_text(route_el, "CommandType")
            if route_plan_id is None or not cmd_type:
                continue
            found_route = True
            results.append(
                RouteActivationRequest(
                    command_id=command_id,
                    mission_plan_id=mission_plan_id,
                    route_plan_id=route_plan_id,
                    command_type=cmd_type,
                    command_state=command_state,
                )
            )
        if found_route:
            continue
        # ByMissionPlan / ByExecutionPlanSet: ActivationCommand applies to
        # the whole plan; Stub tracks it under the MissionPlanID.
        cmd_type = find_text(command_el, "ActivationCommand")
        if not cmd_type:
            continue
        results.append(
            RouteActivationRequest(
                command_id=command_id,
                mission_plan_id=mission_plan_id,
                route_plan_id=mission_plan_id,
                command_type=cmd_type,
                command_state=command_state,
            )
        )
    return results


_SEVERE_WEATHER = frozenset({"SEVERE", "EXTREME"})


@dataclass(frozen=True)
class WeatherAreaData:
    """WeatherAreaData override from RoutePlanValidationCommand Inputs.

    Schema: override of UCI weather messages for this validation.
    ``source`` is required on the type. Icing and turbulence are the
    flyability fields Isolator applies.
    """

    source: str
    icing: str | None = None
    turbulence: str | None = None


def weather_blocks_route(weather: WeatherAreaData | None) -> bool:
    """True when override weather makes the route INVALID.

    Missing override is not a block. Missing Source on a present
    WeatherAreaData is a block. SEVERE / EXTREME icing or
    turbulence is a block.
    """
    if weather is None:
        return False
    if not weather.source:
        return True
    return (weather.icing or "").upper() in _SEVERE_WEATHER or (
        weather.turbulence or ""
    ).upper() in _SEVERE_WEATHER


def _parse_weather_area(data: ET.Element) -> WeatherAreaData | None:
    node = find_one(data, "WeatherAreaData")
    if node is None:
        return None
    return WeatherAreaData(
        source=find_text(node, "Source") or "",
        icing=find_text(node, "Icing"),
        turbulence=find_text(node, "Turbulence"),
    )


@dataclass(frozen=True)
class RouteValidationCommand:
    """Parsed RoutePlanValidationCommand."""

    command_id: UUID
    route_plan_id: UUID | None
    command_state: str = "NEW"
    for_planning_use_only: bool = False
    request_frequency: str = "SINGLE"
    weather: WeatherAreaData | None = None


def parse_route_validation_command(
    xml: str | bytes,
) -> RouteValidationCommand | None:
    """Extract CommandID + RoutePlanID; None if CommandID missing."""
    root = parse_xml(xml)
    if local_name(root) != "RoutePlanValidationCommand":
        raise ValueError(
            f"expected RoutePlanValidationCommand, got {local_name(root)}"
        )
    data = find_one(root, "MessageData")
    if data is None:
        raise ValueError("RoutePlanValidationCommand missing MessageData")
    command_id = uuid_under(data, "CommandID")
    if command_id is None:
        return None
    freq = find_text(data, "RequestFrequencyType") or "SINGLE"
    planning = (find_text(data, "ForPlanningUseOnly") or "false").lower()
    return RouteValidationCommand(
        command_id=command_id,
        route_plan_id=uuid_under(data, "RoutePlanID"),
        command_state=find_text(data, "CommandState") or "NEW",
        for_planning_use_only=planning in {"1", "true", "yes"},
        request_frequency=freq,
        weather=_parse_weather_area(data),
    )


def build_route_plan_validation(
    identity: SystemIdentity,
    *,
    validation_id: UUID,
    route_plan_id: UUID,
    validation_state: str,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build RoutePlanValidation (VALID / INVALID)."""
    data = el(
        "MessageData",
        id_type("RoutePlanValidationID", validation_id),
        id_type("PlanID", route_plan_id),
        el(
            "Validator",
            el("NonOperatorIdentifier", system_id(identity)),
        ),
        el("ValidationState", text=validation_state),
    )
    root = message_envelope(
        "RoutePlanValidation",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
        object_state="NEW",
    )
    return tostring(root)


def build_route_plan_validation_command_status(
    identity: SystemIdentity,
    *,
    command_id: UUID,
    processing_state: str,
    command_status: str | None = None,
    validation_id: UUID | None = None,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build RoutePlanValidationCommandStatus."""
    children = [
        id_type("CommandID", command_id),
        el("CommandProcessingState", text=processing_state),
    ]
    if command_status is not None:
        children.append(el("CommandStatus", text=command_status))
    if validation_id is not None:
        children.append(id_type("RoutePlanValidationID", validation_id))
    data = el("MessageData", *children)
    root = message_envelope(
        "RoutePlanValidationCommandStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_sample_route_validation_command(
    identity: SystemIdentity,
    *,
    command_id: UUID,
    route_plan_id: UUID,
    planning_process_id: UUID | None = None,
    weather_source: str | None = None,
    icing: str | None = None,
    turbulence: str | None = None,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal RoutePlanValidationCommand for unit tests."""
    process_id = planning_process_id or command_id
    inputs_kids = [
        id_type("PlanningProcessID", process_id),
        el("ModifyToValidate", text="false"),
    ]
    if (
        weather_source is not None
        or icing is not None
        or turbulence is not None
    ):
        weather_kids = []
        if weather_source is not None:
            weather_kids.append(el("Source", text=weather_source))
        if icing is not None:
            weather_kids.append(el("Icing", text=icing))
        if turbulence is not None:
            weather_kids.append(el("Turbulence", text=turbulence))
        inputs_kids.append(el("WeatherAreaData", *weather_kids))
    inputs_kids.append(
        el(
            "RoutePlanDetails",
            id_type("RoutePlanID", route_plan_id),
        )
    )
    data = el(
        "MessageData",
        id_type("CommandID", command_id),
        el("CommandState", text="NEW"),
        el("ForPlanningUseOnly", text="false"),
        el("RequestFrequencyType", text="SINGLE"),
        el("Inputs", *inputs_kids),
    )
    root = message_envelope(
        "RoutePlanValidationCommand",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


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


def parse_route_plan_waypoints(xml: str | bytes) -> tuple[Waypoint, ...]:
    """Extract Path / Point2D waypoints from stored MA_RoutePlan XML.

    Returns an empty tuple when MessageData is missing or has no
    geometry. Radians on the wire become degrees on
    :class:`~open_vi.domain.Waypoint`.
    """
    root = parse_xml(xml)
    data = find_one(root, "MessageData")
    if data is None:
        return ()
    return parse_path_waypoints(data)


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
    status_kids = [
        el("CommandProcessingState", text=processing),
        el("CommandStatus", text=command_status),
    ]
    if result.reason:
        reason_kids = [el("Reason", text=result.reason)]
        if result.reason_description:
            reason_kids.append(
                el("Description", text=result.reason_description)
            )
        status_kids.append(el("CommandProcessingStateReason", *reason_kids))
    status = el("ActivationStatus", *status_kids)
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


def build_mission_plan_activation_status(
    identity: SystemIdentity,
    *,
    mission_plan_id: UUID,
    plan_activation_state: str,
    route_plan_id: UUID | None = None,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build ``MissionPlanActivationStatus`` for a mission and route.

    *plan_activation_state* is a ``PlanActivationStateEnum`` token
    (``DEACTIVATED`` after inbound DEACTIVATE). When *route_plan_id*
    is set, ``SubPlanActivationState`` lists that route in the same
    state.
    """
    children = [
        id_type("MissionPlanID", mission_plan_id),
        el("PlanActivationState", text=plan_activation_state),
    ]
    if route_plan_id is not None:
        children.append(
            el(
                "SubPlanActivationState",
                el("ActivationState", text=plan_activation_state),
                el("Plans", id_type("RoutePlanID", route_plan_id)),
            )
        )
    data = el("MessageData", *children)
    root = message_envelope(
        "MissionPlanActivationStatus",
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


def build_sample_by_mission_plan_activation_command(
    identity: SystemIdentity,
    *,
    command_id: UUID,
    mission_plan_id: UUID,
    command_type: str,
    command_state: str = "NEW",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal ByMissionPlan activation command (harness CAL shape)."""
    command = el(
        "Command",
        id_type("MissionPlanID", mission_plan_id),
        el(
            "ActivationDetails",
            el(
                "ByMissionPlan",
                el("ActivationCommand", text=command_type),
                el("CommandSubordinatePlans", text="true"),
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


_SAMPLE_WAYPOINT = Waypoint(
    latitude_deg=38.0, longitude_deg=-77.0, altitude_m=100.0
)


def build_sample_route_plan(
    identity: SystemIdentity,
    *,
    route_plan_id: UUID,
    waypoints: tuple[Waypoint, ...] | None = None,
    path_type: str = "PRIMARY",
    airfield_id: UUID | None = None,
    runway_id: UUID | None = None,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal MA_RoutePlan for unit tests (RoutePlanID + Path).

    *waypoints* defaults to the same sample point FlightCommand uses.
    Pass an empty tuple for a plan with no geometry. *path_type*,
    *airfield_id*, and *runway_id* mark a linked takeoff or landing
    path.
    """
    path_points = (_SAMPLE_WAYPOINT,) if waypoints is None else waypoints
    data_kids = [
        id_type("RoutePlanID", route_plan_id),
        el("ForPlanningUseOnly", text="false"),
    ]
    if path_points:
        data_kids.append(
            build_path_element(
                path_points,
                path_type=path_type,
                airfield_id=airfield_id,
                runway_id=runway_id,
            )
        )
    data = el("MessageData", *data_kids)
    root = message_envelope(
        "MA_RoutePlan",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
        object_state="NEW",
    )
    return tostring(root)
