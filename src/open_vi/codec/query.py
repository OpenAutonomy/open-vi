"""Parse/build QueryDataRequest* and AirfieldReport query outs."""

from __future__ import annotations

from uuid import UUID, uuid4

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
from open_vi.identity import SystemIdentity

_QUERY_KIND = {
    "MA_FLIGHT_CAPABILITY": "capability",
    "FLIGHT_CAPABILITY": "capability",
    "MA_ROUTE_PLAN": "route",
    "ROUTE_PLAN": "route",
    "AIRFIELD_REPORT": "airfield",
}


def parse_query_kinds(xml: str | bytes) -> tuple[str, ...]:
    """Return query kinds from QueryMessage/MessageType (may be empty = all)."""
    root = parse_xml(xml)
    data = find_one(root, "MessageData")
    if data is None:
        return ()
    query = find_one(data, "QueryMessage")
    if query is None:
        return ()
    kinds: list[str] = []
    for node in find_all(query, "MessageType"):
        raw = (node.text or "").strip().upper().replace("-", "_")
        kind = _QUERY_KIND.get(raw)
        if kind and kind not in kinds:
            kinds.append(kind)
    return tuple(kinds)


def build_query_data_request_status(
    identity: SystemIdentity,
    *,
    request_id: UUID,
    processing_state: str = "COMPLETED",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build QueryDataRequestStatus (Loose: no Result / native pages)."""
    data = el(
        "MessageData",
        id_type("RequestID", request_id),
        el("RequestProcessingState", text=processing_state),
    )
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
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal QueryDataRequest for unit tests."""
    query_kids = [el("MessageType", text=mt) for mt in message_types]
    data = el(
        "MessageData",
        id_type("RequestID", request_id),
        el("RequestState", text="NEW"),
        el("QueryMessage", *query_kids),
        system_id(identity),
    )
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
    report_id: UUID | None = None,
    airfield_id: UUID | None = None,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal AirfieldReport (self-reported home field)."""
    data = el(
        "MessageData",
        id_type("AirfieldReportID", report_id or uuid4(), "airfield-report"),
        id_type("AirfieldID", airfield_id or uuid4(), "home-field"),
        el("IdentityReferenceID", system_id(identity)),
        el("ObservationTime", text=utc_now()),
    )
    root = message_envelope(
        "AirfieldReport",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
        object_state="NEW",
    )
    return tostring(root)
