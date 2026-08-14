"""Parse MA_FlightCommand; build Status and Activity replies."""

from __future__ import annotations

from uuid import UUID

from open_vi.codec.geo import deg_to_rad, format_uci_angle, rad_to_deg
from open_vi.codec.ns import SCHEMA_VERSION
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
from open_vi.identity import SystemIdentity
from open_vi.platform.port import (
    CommandResult,
    FlightActivitySnapshot,
    FlightCommandRequest,
    Waypoint,
)

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
        state = find_text(choice_el, "CommandState") or "NEW"
        mode = None
        for tag, mode_name in _MODE_TAGS.items():
            if find_one(choice_el, tag) is not None:
                mode = mode_name
                break
        waypoints = _parse_waypoints(choice_el)
        requests.append(
            FlightCommandRequest(
                command_id=parse_uuid_text(command_id_text),
                capability_id=parse_uuid_text(cap_id_text),
                command_state=state,
                mode=mode,
                waypoints=waypoints,
                choice=choice_name,
            )
        )
    return requests


def _parse_waypoints(node) -> tuple[Waypoint, ...]:
    """Extract waypoints; UCI lat/lon are radians on the wire.

    A-GRA PathSegment lists are not necessarily in flight order. Walk
    ``FirstInPathSegmentID`` / ``NextPathSegment`` when present (MA's
    ``EndPoint`` / ``Point2D`` layout). Fall back to document-order
    ``Position`` / ``Point2D`` for older sample XML.
    """
    chained = _waypoints_from_path_links(node)
    if chained:
        return chained
    return _waypoints_document_order(node)


def _hex_id(text: str | None) -> str | None:
    if not text:
        return None
    return text.replace("-", "").strip().lower()


def _direct_named(node, *names):
    wanted = set(names)
    return [child for child in list(node) if local_name(child) in wanted]


def _waypoints_from_path_links(node) -> tuple[Waypoint, ...]:
    points: list[Waypoint] = []
    for path in (child for child in node.iter() if local_name(child) == "Path"):
        points.extend(_path_segment_waypoints(path))
    return tuple(points)


def _path_segment_waypoints(path) -> list[Waypoint]:
    segs = _direct_named(path, "PathSegment", "Segment")
    if not segs:
        return []
    by_id: dict[str, object] = {}
    for seg in segs:
        sid_node = find_one(seg, "PathSegmentID")
        sid = _hex_id(
            find_text(sid_node, "UUID") if sid_node is not None else None
        )
        if sid:
            by_id[sid] = seg
    start = None
    for child in list(path):
        if local_name(child) == "FirstInPathSegmentID":
            start = _hex_id(find_text(child, "UUID"))
            break
    ordered: list = []
    seen: set[str] = set()
    cur = start
    while cur and cur not in seen:
        seen.add(cur)
        seg = by_id.get(cur)
        if seg is None:
            break
        ordered.append(seg)
        nxt = None
        for child in list(seg):
            if local_name(child) == "NextPathSegment":
                nxt = child
                break
        cur = None
        if nxt is not None:
            nid_node = find_one(nxt, "PathSegmentID")
            nid = find_text(nid_node, "UUID") if nid_node is not None else None
            cur = _hex_id(nid)
    if not ordered:
        ordered = segs
    points: list[Waypoint] = []
    for seg in ordered:
        wp = _waypoint_from_segment(seg)
        if wp is not None:
            points.append(wp)
    return points


def _waypoint_from_segment(seg) -> Waypoint | None:
    point = None
    for candidate in seg.iter():
        if local_name(candidate) in {"Point2D", "Position"}:
            point = candidate
            break
    if point is None:
        return None
    lat_text = find_text(point, "Latitude")
    lon_text = find_text(point, "Longitude")
    if not lat_text or not lon_text:
        return None
    alt_text = find_text(point, "Altitude")
    return Waypoint(
        latitude_deg=rad_to_deg(float(lat_text)),
        longitude_deg=rad_to_deg(float(lon_text)),
        altitude_m=float(alt_text) if alt_text else None,
    )


def _waypoints_document_order(node) -> tuple[Waypoint, ...]:
    """Scan nested Position/Point2D when no PathSegment chain exists."""
    points: list[Waypoint] = []
    for candidate in node.iter():
        lat_text = None
        lon_text = None
        alt_text = None
        for child in list(candidate):
            name = local_name(child)
            text = (child.text or "").strip()
            if name == "Latitude":
                lat_text = text
            elif name == "Longitude":
                lon_text = text
            elif name == "Altitude":
                alt_text = text
        if not lat_text or not lon_text:
            continue
        points.append(
            Waypoint(
                latitude_deg=rad_to_deg(float(lat_text)),
                longitude_deg=rad_to_deg(float(lon_text)),
                altitude_m=float(alt_text) if alt_text else None,
            )
        )
    return tuple(points)


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


def _capability_shell(
    command_id: UUID,
    capability_id: UUID,
    flight_control_mode,
):
    return el(
        "Capability",
        id_type("CommandID", command_id),
        el("CommandState", text="NEW"),
        id_type("CapabilityID", capability_id, "flight-capability"),
        el(
            "Ranking",
            el(
                "Rank",
                el("Priority", text="0"),
                el("PrecedenceWithinPriority", text="0"),
            ),
        ),
        el("FlightControlMode", flight_control_mode),
    )


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
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal MA_FlightCommand (WaypointFollowing) for unit tests."""
    path_id = UUID(int=1)
    path_children = [
        id_type("PathID", path_id, "path-1"),
        el("PathType", text="PRIMARY"),
    ]
    for index, wp in enumerate(waypoints, start=1):
        point_kids = [
            el("Latitude", text=format_uci_angle(deg_to_rad(wp.latitude_deg))),
            el(
                "Longitude",
                text=format_uci_angle(deg_to_rad(wp.longitude_deg)),
            ),
        ]
        if wp.altitude_m is not None:
            point_kids.append(el("Altitude", text=str(wp.altitude_m)))
        path_children.append(
            el(
                "Segment",
                id_type("PathSegmentID", UUID(int=index)),
                el("Position", *point_kids),
            )
        )
    route = el(
        "Route",
        el("Detailed", text="false"),
        id_type("FirstInRoutePathID", path_id),
        el("RouteProjection", text="GREAT_CIRCLE"),
        el("Path", *path_children),
    )
    capability = _capability_shell(
        command_id, capability_id, el("WaypointFollowing", route)
    )
    return _flight_command_bytes(
        identity, capability, schema_version=schema_version, mode=mode
    )


def build_sample_hsa_csa_command(
    identity: SystemIdentity,
    *,
    command_id: UUID,
    capability_id: UUID,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal MA_FlightCommand (empty HSA_CSA) for unit tests."""
    capability = _capability_shell(command_id, capability_id, el("HSA_CSA"))
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
