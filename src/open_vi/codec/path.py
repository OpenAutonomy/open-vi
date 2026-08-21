"""Parse and build A-GRA Path / Point2D waypoint lists.

UCI lat/lon are radians on the wire; :class:`~open_vi.domain.Waypoint`
uses degrees. FlightCommand and MA_RoutePlan share this walker.
"""

from __future__ import annotations

from uuid import UUID

from open_vi.codec.geo import deg_to_rad, format_uci_angle, rad_to_deg
from open_vi.codec.xmlutil import el, find_one, find_text, id_type, local_name
from open_vi.domain import Waypoint


def parse_path_waypoints(node) -> tuple[Waypoint, ...]:
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


def build_path_element(waypoints: tuple[Waypoint, ...]):
    """Build a Path element (PathID, PathType, Segment children)."""
    path_id = UUID(int=1)
    children = [
        id_type("PathID", path_id, "path-1"),
        el("PathType", text="PRIMARY"),
    ]
    for index, waypoint in enumerate(waypoints, start=1):
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
        children.append(
            el(
                "Segment",
                id_type("PathSegmentID", UUID(int=index)),
                el("Position", *point_kids),
            )
        )
    return el("Path", *children)


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
        waypoint = _waypoint_from_segment(seg)
        if waypoint is not None:
            points.append(waypoint)
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
