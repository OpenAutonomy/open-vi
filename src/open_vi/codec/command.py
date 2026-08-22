"""Parse MA_FlightCommand; build Status and Activity replies."""

from __future__ import annotations

from uuid import UUID

from open_vi.codec.geo import deg_to_rad, format_uci_angle, rad_to_deg
from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.path import build_path_element, parse_path_waypoints
from open_vi.codec.xmlutil import (
    el,
    find_all,
    find_one,
    find_text,
    id_type,
    local_name,
    message_envelope,
    parse_uuid_text,
    parse_xml,
    tostring,
)
from open_vi.domain import (
    CommandResult,
    FlightActivitySnapshot,
    FlightCommandRequest,
    HsaCsaSetpoint,
    Waypoint,
)
from open_vi.identity import SystemIdentity

_MODE_TAGS = {
    "WaypointFollowing": "WAYPOINT_FOLLOWING",
    "HSA_CSA": "HSA_CSA",
    "CurveFollowing": "CURVE_FOLLOWING",
}


def parse_flight_commands(xml: str | bytes) -> list[FlightCommandRequest]:
    """Extract Capability/Activity command instances from FlightCommand."""
    root = parse_xml(xml)
    if local_name(root) != "MA_FlightCommand":
        raise ValueError(f"expected MA_FlightCommand, got {local_name(root)}")
    data = find_one(root, "MessageData")
    if data is None:
        raise ValueError("MA_FlightCommand missing MessageData")
    requests: list[FlightCommandRequest] = []
    for command in find_all(data, "Command"):
        # Command wraps Capability | Activity choice; find_all is deep, so
        # take the direct choice child under this Command element.
        choice_el = None
        choice_name = None
        for child in list(command):
            name = local_name(child)
            if name in {"Capability", "Activity"}:
                choice_el = child
                choice_name = name
                break
        if choice_el is None or choice_name is None:
            continue
        cmd_id_node = find_one(choice_el, "CommandID")
        command_id_text = (
            find_text(cmd_id_node, "UUID") if cmd_id_node is not None else None
        )
        if not command_id_text:
            raise ValueError("FlightCommand missing CommandID/UUID")
        cap_id_node = find_one(choice_el, "CapabilityID")
        cap_id_text = (
            find_text(cap_id_node, "UUID") if cap_id_node is not None else None
        )
        if not cap_id_text:
            # Activity commands may omit CapabilityID; use nil for reject path.
            cap_id_text = "0" * 32
        activity_id = None
        if choice_name == "Activity":
            act_id_node = find_one(choice_el, "ActivityID")
            act_id_text = (
                find_text(act_id_node, "UUID")
                if act_id_node is not None
                else None
            )
            if act_id_text:
                activity_id = parse_uuid_text(act_id_text)
        state = find_text(choice_el, "CommandState") or "NEW"
        mode = None
        for tag, mode_name in _MODE_TAGS.items():
            if find_one(choice_el, tag) is not None:
                mode = mode_name
                break
        waypoints = parse_path_waypoints(choice_el)
        hsa = parse_hsa_csa(choice_el) if mode == "HSA_CSA" else None
        requests.append(
            FlightCommandRequest(
                command_id=parse_uuid_text(command_id_text),
                capability_id=parse_uuid_text(cap_id_text),
                command_state=state,
                mode=mode,
                waypoints=waypoints,
                choice=choice_name,
                activity_id=activity_id,
                hsa=hsa,
            )
        )
    return requests


def parse_hsa_csa(node) -> HsaCsaSetpoint:
    """Parse ``HSA_CSA`` altitude / speed / direction under *node*.

    Degrees in the returned setpoint. Mach and SpeedOptimization are
    flagged ``unsupported`` — no conversion is invented.
    """
    hsa_el = find_one(node, "HSA_CSA")
    if hsa_el is None:
        return HsaCsaSetpoint()
    if find_one(hsa_el, "MachValue") is not None:
        return HsaCsaSetpoint(unsupported="MACH")
    if find_one(hsa_el, "SpeedOptimization") is not None:
        return HsaCsaSetpoint(unsupported="SPEED_OPTIMIZATION")
    altitude_m = None
    altitude_ref = None
    alt_wrap = None
    for child in list(hsa_el):
        if local_name(child) == "Altitude":
            alt_wrap = child
            break
    if alt_wrap is not None:
        for child in list(alt_wrap):
            name = local_name(child)
            if name == "AltitudeReference" and child.text:
                altitude_ref = child.text.strip()
            elif name == "Altitude" and child.text:
                altitude_m = float(child.text.strip())
    speed_mps = None
    speed_ref = None
    speed_value = find_one(hsa_el, "SpeedValue")
    if speed_value is not None:
        speed_text = find_text(speed_value, "Value")
        if speed_text:
            speed_mps = float(speed_text)
        speed_ref = find_text(speed_value, "Reference")
    heading_deg = None
    direction_kind = None
    heading_ref = None
    direction = find_one(hsa_el, "Direction")
    if direction is not None:
        choice = None
        for child in list(direction):
            name = local_name(child)
            if name in {"Heading", "Course"}:
                choice = child
                direction_kind = name.upper()
                break
        if choice is not None:
            heading_ref = find_text(choice, "Reference")
            value_text = find_text(choice, "Value")
            if value_text:
                heading_deg = rad_to_deg(float(value_text))
    return HsaCsaSetpoint(
        altitude_m=altitude_m,
        altitude_ref=altitude_ref,
        speed_mps=speed_mps,
        speed_ref=speed_ref,
        heading_deg=heading_deg,
        direction_kind=direction_kind,
        heading_ref=heading_ref,
    )


def build_flight_command_status(
    identity: SystemIdentity,
    *,
    command_id: UUID,
    result: CommandResult,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build MA_FlightCommandStatus for an accept/reject decision."""
    children = [
        id_type("CommandID", command_id),
        el("CommandProcessingState", text=result.processing_state),
    ]
    if result.reason:
        reason_kids = [el("Reason", text=result.reason)]
        if result.reason_description:
            reason_kids.append(
                el("Description", text=result.reason_description)
            )
        children.append(el("CommandProcessingStateReason", *reason_kids))
    if result.validation_results:
        detail_kids = [
            el("ValidationResult", text=value)
            for value in result.validation_results
        ]
        if result.reason_description:
            detail_kids.append(
                el(
                    "ValidationResultReason",
                    el("Description", text=result.reason_description),
                )
            )
        children.append(el("CannotComplyDetails", *detail_kids))
    if result.processing_state == "ACCEPTED" and result.activity_id is not None:
        children.append(
            el(
                "Activity",
                id_type("ActivityID", result.activity_id),
                el(
                    "NewActivity",
                    text="true" if result.new_activity else "false",
                ),
            )
        )
    data = el("MessageData", *children)
    root = message_envelope(
        "MA_FlightCommandStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_flight_activity(
    identity: SystemIdentity,
    activity: FlightActivitySnapshot,
    *,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
    object_state: str = "NEW",
) -> bytes:
    """Build MA_FlightActivity for an accepted flight command."""
    activity_el = el(
        "Activity",
        id_type("ActivityID", activity.activity_id, "flight-activity"),
        id_type("CapabilityID", activity.capability_id, "flight-capability"),
        el("Interactive", text="true" if activity.interactive else "false"),
        el("ActivityState", text=activity.activity_state),
        el("VehicleCommandState"),
    )
    data = el("MessageData", activity_el)
    root = message_envelope(
        "MA_FlightActivity",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
        object_state=object_state,
    )
    return tostring(root)


def _ranking():
    return el(
        "Ranking",
        el(
            "Rank",
            el("Priority", text="0"),
            el("PrecedenceWithinPriority", text="0"),
        ),
    )


def _capability_shell(
    command_id: UUID,
    capability_id: UUID,
    flight_control_mode,
    *,
    command_state: str = "NEW",
):
    return el(
        "Capability",
        id_type("CommandID", command_id),
        el("CommandState", text=command_state),
        id_type("CapabilityID", capability_id, "flight-capability"),
        _ranking(),
        el("FlightControlMode", flight_control_mode),
    )


def _activity_shell(
    command_id: UUID,
    activity_id: UUID,
    flight_control_mode,
    *,
    command_state: str = "UPDATE",
    capability_id: UUID | None = None,
):
    children = [
        id_type("CommandID", command_id),
        el("CommandState", text=command_state),
        id_type("ActivityID", activity_id, "flight-activity"),
    ]
    if capability_id is not None:
        children.append(
            id_type("CapabilityID", capability_id, "flight-capability")
        )
    children.extend((_ranking(), el("FlightControlMode", flight_control_mode)))
    return el("Activity", *children)


def _hsa_csa_mode(
    *,
    heading_deg: float | None,
    speed_mps: float | None,
    altitude_m: float | None,
    altitude_ref: str = "AGL",
    speed_ref: str = "GROUNDSPEED",
    heading_ref: str = "TRUE_NORTH",
    direction_kind: str = "HEADING",
    include_mach: bool = False,
):
    """Build an ``HSA_CSA`` FlightControlMode element."""
    kids = []
    if altitude_m is not None:
        kids.append(
            el(
                "Altitude",
                el("AltitudeReference", text=altitude_ref),
                el("Altitude", text=str(altitude_m)),
            )
        )
    if include_mach:
        kids.append(el("Speed", el("SpeedChoice", el("MachValue", text="0.2"))))
    elif speed_mps is not None:
        kids.append(
            el(
                "Speed",
                el(
                    "SpeedChoice",
                    el(
                        "SpeedValue",
                        el("Value", text=str(speed_mps)),
                        el("Reference", text=speed_ref),
                    ),
                ),
            )
        )
    if heading_deg is not None:
        tag = "Course" if direction_kind == "COURSE" else "Heading"
        kids.append(
            el(
                "Direction",
                el(
                    tag,
                    el(
                        "Value",
                        text=format_uci_angle(deg_to_rad(heading_deg)),
                    ),
                    el("Reference", text=heading_ref),
                ),
            )
        )
    return el("HSA_CSA", *kids)


def _waypoint_following_mode(waypoints: tuple[Waypoint, ...]):
    path = build_path_element(waypoints)
    path_id = UUID(int=1)
    route = el(
        "Route",
        el("Detailed", text="false"),
        id_type("FirstInRoutePathID", path_id),
        el("RouteProjection", text="GREAT_CIRCLE"),
        path,
    )
    return el("WaypointFollowing", route)


def _flight_command_bytes(
    identity: SystemIdentity,
    capability,
    *,
    schema_version: str,
    mode: str,
) -> bytes:
    data = el("MessageData", el("Command", capability))
    root = message_envelope(
        "MA_FlightCommand",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_sample_waypoint_command(
    identity: SystemIdentity,
    *,
    command_id: UUID,
    capability_id: UUID,
    waypoints: tuple[Waypoint, ...] = (
        Waypoint(latitude_deg=38.0, longitude_deg=-77.0, altitude_m=100.0),
    ),
    command_state: str = "NEW",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal MA_FlightCommand (WaypointFollowing) for unit tests."""
    capability = _capability_shell(
        command_id,
        capability_id,
        _waypoint_following_mode(waypoints),
        command_state=command_state,
    )
    return _flight_command_bytes(
        identity, capability, schema_version=schema_version, mode=mode
    )


def build_sample_activity_update_command(
    identity: SystemIdentity,
    *,
    command_id: UUID,
    activity_id: UUID,
    waypoints: tuple[Waypoint, ...] = (
        Waypoint(latitude_deg=38.0, longitude_deg=-77.0, altitude_m=100.0),
    ),
    command_state: str = "UPDATE",
    capability_id: UUID | None = None,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal Activity-choice MA_FlightCommand (UPDATE) for unit tests."""
    activity = _activity_shell(
        command_id,
        activity_id,
        _waypoint_following_mode(waypoints),
        command_state=command_state,
        capability_id=capability_id,
    )
    return _flight_command_bytes(
        identity, activity, schema_version=schema_version, mode=mode
    )


def build_sample_hsa_csa_command(
    identity: SystemIdentity,
    *,
    command_id: UUID,
    capability_id: UUID,
    heading_deg: float | None = 90.0,
    speed_mps: float | None = 5.0,
    altitude_m: float | None = 50.0,
    altitude_ref: str = "AGL",
    speed_ref: str = "GROUNDSPEED",
    heading_ref: str = "TRUE_NORTH",
    direction_kind: str = "HEADING",
    include_mach: bool = False,
    command_state: str = "NEW",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal MA_FlightCommand (HSA_CSA vector) for unit tests."""
    capability = _capability_shell(
        command_id,
        capability_id,
        _hsa_csa_mode(
            heading_deg=heading_deg,
            speed_mps=speed_mps,
            altitude_m=altitude_m,
            altitude_ref=altitude_ref,
            speed_ref=speed_ref,
            heading_ref=heading_ref,
            direction_kind=direction_kind,
            include_mach=include_mach,
        ),
        command_state=command_state,
    )
    return _flight_command_bytes(
        identity, capability, schema_version=schema_version, mode=mode
    )


def build_sample_curve_following_command(
    identity: SystemIdentity,
    *,
    command_id: UUID,
    capability_id: UUID,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal MA_FlightCommand (CurveFollowing NURBS spine) for unit tests."""
    frame_id = UUID(int=99)
    control_points = []
    for index in range(4):
        control_points.append(
            el(
                "ControlPoints",
                el(
                    "ControlPoint",
                    id_type("ReferenceFrameID", frame_id),
                    el(
                        "RelativeOffset",
                        el("Rotation", text="UNROTATED"),
                        el("XY_Offsets", text="CARTESIAN"),
                        el("X", text=str(float(index * 100))),
                        el("Y", text="0"),
                    ),
                ),
                el("Weight", text="1"),
            )
        )
    knots = [el("KnotVector", text=str(k)) for k in (0, 0, 1, 1)]
    segment = el(
        "CurveSegments",
        el(
            "CenterReference",
            el(
                "Point2D",
                el(
                    "Latitude",
                    text=format_uci_angle(deg_to_rad(38.8895)),
                ),
                el(
                    "Longitude",
                    text=format_uci_angle(deg_to_rad(-77.0353)),
                ),
            ),
        ),
        *control_points,
        *knots,
    )
    capability = _capability_shell(
        command_id, capability_id, el("CurveFollowing", segment)
    )
    return _flight_command_bytes(
        identity, capability, schema_version=schema_version, mode=mode
    )
