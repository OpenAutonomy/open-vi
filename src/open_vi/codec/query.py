"""Parse/build QueryDataRequest* and AirfieldReport query outs."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID, uuid4

from open_vi.codec.geo import deg_to_rad, format_uci_angle
from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.xmlutil import (
    el,
    find_all,
    find_one,
    id_type,
    message_envelope,
    parse_xml,
    system_id,
    tostring,
    utc_now,
)
from open_vi.domain import HomeAirfield, Waypoint
from open_vi.identity import SystemIdentity

_QUERY_KIND = {
    "MA_FLIGHT_CAPABILITY": "capability",
    "FLIGHT_CAPABILITY": "capability",
    "MA_ROUTE_PLAN": "route",
    "ROUTE_PLAN": "route",
    "AIRFIELD_REPORT": "airfield",
}


@dataclass(frozen=True)
class QueryRequest:
    """Parsed QueryDataRequest filter (kinds + identifiers-only)."""

    kinds: tuple[str, ...]
    identifiers_only: bool = False


def parse_query_kinds(xml: str | bytes) -> tuple[str, ...]:
    """Return query kinds from QueryMessage/MessageType (may be empty = all)."""
    return parse_query_request(xml).kinds


def parse_query_request(xml: str | bytes) -> QueryRequest:
    """Parse MessageType kinds and ``QueryIdentifiersOnly``."""
    root = parse_xml(xml)
    data = find_one(root, "MessageData")
    if data is None:
        return QueryRequest(kinds=())
    identifiers_only = find_one(data, "QueryIdentifiersOnly") is not None
    query = find_one(data, "QueryMessage")
    if query is None:
        return QueryRequest(kinds=(), identifiers_only=identifiers_only)
    kinds: list[str] = []
    for node in find_all(query, "MessageType"):
        raw = (node.text or "").strip().upper().replace("-", "_")
        kind = _QUERY_KIND.get(raw)
        if kind and kind not in kinds:
            kinds.append(kind)
    return QueryRequest(kinds=tuple(kinds), identifiers_only=identifiers_only)


def build_query_data_request_status(
    identity: SystemIdentity,
    *,
    request_id: UUID,
    processing_state: str = "COMPLETED",
    result_ids: tuple[tuple[UUID, str], ...] = (),
    reason: str | None = None,
    reason_description: str | None = None,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build QueryDataRequestStatus.

    *result_ids* is ``(uuid, label)`` pairs under ``Result/ID``.
    Used on ``COMPLETED``. *reason* is
    ``RequestProcessingStateReason`` (``FAILED``).
    """
    children = [
        id_type("RequestID", request_id),
        el("RequestProcessingState", text=processing_state),
    ]
    if reason:
        reason_kids = [el("Reason", text=reason)]
        if reason_description:
            reason_kids.append(el("Description", text=reason_description))
        children.append(el("RequestProcessingStateReason", *reason_kids))
    if result_ids:
        children.append(
            el(
                "Result",
                *[id_type("ID", value, label) for value, label in result_ids],
            )
        )
    data = el("MessageData", *children)
    root = message_envelope(
        "QueryDataRequestStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_sample_query_data_request(
    identity: SystemIdentity,
    *,
    request_id: UUID,
    message_types: tuple[str, ...] = ("MA_FLIGHT_CAPABILITY",),
    identifiers_only: bool = False,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal QueryDataRequest for unit tests."""
    query_kids = [el("MessageType", text=mt) for mt in message_types]
    data_kids = [
        id_type("RequestID", request_id),
        el("RequestState", text="NEW"),
    ]
    if identifiers_only:
        data_kids.append(el("QueryIdentifiersOnly"))
    data_kids.append(el("QueryMessage", *query_kids))
    data_kids.append(system_id(identity))
    data = el("MessageData", *data_kids)
    root = message_envelope(
        "QueryDataRequest",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_airfield_report(
    identity: SystemIdentity,
    *,
    airfield: HomeAirfield | None = None,
    report_id: UUID | None = None,
    airfield_id: UUID | None = None,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Self-reported home ``AirfieldReport``.

    When *airfield* is set, ``Information/Runway`` includes direction,
    length, and takeoff/landing Start+Limit coordinates.
    """
    report = (
        airfield.report_id if airfield is not None else report_id
    ) or uuid4()
    field_id = (
        airfield.airfield_id if airfield is not None else airfield_id
    ) or uuid4()
    kids = [
        id_type("AirfieldReportID", report, "airfield-report"),
        id_type("AirfieldID", field_id, "home-field"),
        el("IdentityReferenceID", system_id(identity)),
        el("ObservationTime", text=utc_now()),
    ]
    if airfield is not None:
        kids.append(_airfield_information(airfield))
    data = el("MessageData", *kids)
    root = message_envelope(
        "AirfieldReport",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
        object_state="NEW",
    )
    return tostring(root)


def _airfield_information(airfield: HomeAirfield):
    """Information/Runway geometry for a home field."""
    return el(
        "Information",
        el("Operational"),
        el(
            "Runway",
            id_type("RunwayID", airfield.runway_id, "home-runway"),
            el(
                "Direction",
                text=format_uci_angle(deg_to_rad(airfield.direction_deg)),
            ),
            el("AvailableLength", text=str(airfield.available_length_m)),
            el(
                "TakeoffCoordinates",
                *_runway_coordinates(
                    airfield.takeoff_start, airfield.takeoff_end
                ),
            ),
            el(
                "LandingCoordinates",
                *_runway_coordinates(
                    airfield.landing_start, airfield.landing_end
                ),
            ),
        ),
    )


def _runway_coordinates(start: Waypoint, limit: Waypoint):
    """RunwayCoordinatesType Start + Limit as Point3D."""
    return (
        el("Start", *_point3d(start)),
        el("Limit", *_point3d(limit)),
    )


def _point3d(waypoint: Waypoint):
    """Latitude, Longitude, Altitude children for Point3D."""
    altitude = waypoint.altitude_m if waypoint.altitude_m is not None else 0.0
    return (
        el(
            "Latitude",
            text=format_uci_angle(deg_to_rad(waypoint.latitude_deg)),
        ),
        el(
            "Longitude",
            text=format_uci_angle(deg_to_rad(waypoint.longitude_deg)),
        ),
        el("Altitude", text=str(altitude)),
    )
