"""Parse and build A-GRA Path / Point2D waypoint lists.

UCI lat/lon are radians on the wire; :class:`~open_vi.domain.Waypoint`
uses degrees. FlightCommand and MA_RoutePlan share this walker.
"""

from __future__ import annotations

from uuid import UUID
from xml.etree import ElementTree as ET

from open_vi.codec.geo import deg_to_rad, format_uci_angle, rad_to_deg
from open_vi.codec.xmlutil import el, find_one, find_text, id_type, local_name
from open_vi.domain import Waypoint


def parse_path_waypoints(node: ET.Element) -> tuple[Waypoint, ...]:
    """Extract waypoints from Path / Position / Point2D under *node*.

    A-GRA PathSegment lists are not necessarily in flight order. Walk
    ``FirstInPathSegmentID`` / ``NextPathSegment`` when present (A-GRA
    ``EndPoint`` / ``Point2D`` layout). Fall back to document-order
    ``Position`` / ``Point2D`` for older sample XML.
    """
    chained = _waypoints_from_path_links(node)
    if chained:
        return chained
    return _waypoints_document_order(node)


def segment_id_for_index(index: int) -> UUID:
    """The ``PathSegmentID`` :func:`build_path_element` gives *index*.

    One home for the rule so a status message naming a segment and the
    path that defined it cannot disagree. *index* is 0-based, matching
    :class:`~open_vi.domain.RouteProgress`; the ids themselves are
    1-based.
    """
    return UUID(int=index + 1)


def build_path_element(
    waypoints: tuple[Waypoint, ...],
    *,
    path_type: str = "PRIMARY",
    airfield_id: UUID | None = None,
    runway_id: UUID | None = None,
) -> ET.Element:
    """Build an A-GRA ``Path``: PathID, PathType, then linked PathSegments.

    A-GRA models a path as a linked list: ``FirstInPathSegmentID``
    names the head, and each ``PathSegment`` points at its successor
    through ``NextPathSegment``. Each segment carries its position
    under ``EndPoint/WayPoint/PointChoice/Point2D``.

    *path_type* is a PathTypeEnum token (``PRIMARY``, ``TAKEOFF``,
    ``LANDING``). *airfield_id* / *runway_id* link TO/L paths to the
    home ``AirfieldReport``.

    Segment ids are ``UUID(int=index)``, 1-based, so a built path is
    reproducible and a segment can be referenced by index elsewhere —
    ``RoutePlanExecutionStatus/CurrentSegment`` needs exactly that.
    """
    path_id = UUID(int=1)
    segment_ids = [UUID(int=index) for index in range(1, len(waypoints) + 1)]
    children = [
        id_type("PathID", path_id, "path-1"),
        el("PathType", text=path_type),
    ]
    if segment_ids:
        children.append(id_type("FirstInPathSegmentID", segment_ids[0]))
    for index, waypoint in enumerate(waypoints):
        point_kids = [
            el(
                "Latitude",
                text=format_uci_angle(deg_to_rad(waypoint.latitude_deg)),
            ),
            el(
                "Longitude",
                text=format_uci_angle(deg_to_rad(waypoint.longitude_deg)),
            ),
        ]
        if waypoint.altitude_m is not None:
            point_kids.append(el("Altitude", text=str(waypoint.altitude_m)))
        segment_kids = [
            id_type("PathSegmentID", segment_ids[index], f"seg-{index + 1}"),
            el("Source", text="OPERATOR_DEFINED"),
            el(
                "EndPoint",
                el(
                    "WayPoint",
                    el("PointChoice", el("Point2D", *point_kids)),
                    el("WaypointType", text="NAV_ONLY"),
                ),
            ),
        ]
        if index + 1 < len(segment_ids):
            segment_kids.append(
                el(
                    "NextPathSegment",
                    id_type("PathSegmentID", segment_ids[index + 1]),
                )
            )
        children.append(el("PathSegment", *segment_kids))
    if airfield_id is not None:
        children.append(id_type("AirfieldID", airfield_id, "home-field"))
    if runway_id is not None:
        children.append(id_type("RunwayID", runway_id, "home-runway"))
    return el("Path", *children)


def _hex_id(text: str | None) -> str | None:
    if not text:
        return None
    return text.replace("-", "").strip().lower()


def _direct_named(node: ET.Element, *names: str) -> list[ET.Element]:
    wanted = set(names)
    return [child for child in list(node) if local_name(child) in wanted]


def _waypoints_from_path_links(node: ET.Element) -> tuple[Waypoint, ...]:
    points: list[Waypoint] = []
    for path in (child for child in node.iter() if local_name(child) == "Path"):
        points.extend(_path_segment_waypoints(path))
    return tuple(points)


def _path_segment_waypoints(path: ET.Element) -> list[Waypoint]:
    segs = _direct_named(path, "PathSegment", "Segment")
    if not segs:
        return []
    by_id: dict[str, ET.Element] = {}
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
    ordered: list[ET.Element] = []
    seen: set[str] = set()
    cur = start
    while cur and cur not in seen:
        seen.add(cur)
        # Distinct name: `seg` above is the non-optional loop variable,
        # and reusing it for this lookup hid that this can miss.
        linked = by_id.get(cur)
        if linked is None:
            break
        ordered.append(linked)
        nxt = None
        for child in linked:
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
        waypoint = _waypoint_from_segment(seg)
        if waypoint is not None:
            points.append(waypoint)
    return points


def _waypoint_from_segment(seg: ET.Element) -> Waypoint | None:
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


def _waypoints_document_order(node: ET.Element) -> tuple[Waypoint, ...]:
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
