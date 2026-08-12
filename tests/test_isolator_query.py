"""Isolator: QueryDataRequest native outs by MessageType."""

from __future__ import annotations

from uuid import uuid4

from isolator_helpers import attach_isolator
from open_vi.asb import InMemoryAsb
from open_vi.codec.query import (
    build_sample_query_data_request,
    parse_query_kinds,
)
from open_vi.codec.route import build_sample_route_plan
from open_vi.codec.xmlutil import local_name, parse_xml
from open_vi.config import IsolatorConfig
from open_vi.isolator import Isolator
from open_vi.isolator.handlers.query import (
    MT_AIRFIELD_REPORT,
    MT_FLIGHT_CAPABILITY,
    MT_QUERY_DATA_REQUEST,
    MT_QUERY_DATA_REQUEST_STATUS,
)
from open_vi.isolator.handlers.route import (
    MT_FILE_LOCATION,
    MT_FILE_METADATA,
    MT_ROUTE_PLAN,
)
from open_vi.platform import StubPlatform


def _iso(bus: InMemoryAsb) -> Isolator:
    return Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(
            tick_republish_status=False,
            publish_vehicle_state=False,
            publish_status_package=False,
        ),
    )


def test_parse_query_kinds() -> None:
    iso = _iso(InMemoryAsb())
    xml = build_sample_query_data_request(
        iso.identity,
        request_id=uuid4(),
        message_types=("MA_ROUTE_PLAN", "AIRFIELD_REPORT"),
    )
    assert parse_query_kinds(xml) == ("route", "airfield")


def test_capability_query_republishes_flight_capability() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    attach_isolator(iso)
    bus.publish(
        MT_QUERY_DATA_REQUEST,
        build_sample_query_data_request(iso.identity, request_id=uuid4()),
    )
    assert len(bus.published[MT_QUERY_DATA_REQUEST_STATUS]) == 2
    cap = bus.published[MT_FLIGHT_CAPABILITY][-1]
    assert local_name(parse_xml(cap)) == "MA_FlightCapability"
    assert iso.ctx.state.capability_id.hex in cap.replace("-", "")
    assert MT_AIRFIELD_REPORT not in bus.published


def test_airfield_query_publishes_report() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    attach_isolator(iso)
    bus.publish(
        MT_QUERY_DATA_REQUEST,
        build_sample_query_data_request(
            iso.identity,
            request_id=uuid4(),
            message_types=("AIRFIELD_REPORT",),
        ),
    )
    report = bus.published[MT_AIRFIELD_REPORT][-1]
    assert local_name(parse_xml(report)) == "AirfieldReport"
    assert "ObservationTime" in report


def test_route_query_returns_file_star_and_plan() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    attach_isolator(iso)
    route_id = uuid4()
    bus.publish(
        MT_ROUTE_PLAN,
        build_sample_route_plan(iso.identity, route_plan_id=route_id),
    )
    before_files = len(bus.published[MT_FILE_LOCATION])
    bus.publish(
        MT_QUERY_DATA_REQUEST,
        build_sample_query_data_request(
            iso.identity,
            request_id=uuid4(),
            message_types=("MA_ROUTE_PLAN",),
        ),
    )
    assert len(bus.published[MT_FILE_LOCATION]) == before_files + 1
    assert len(bus.published[MT_FILE_METADATA]) == before_files + 1
    assert route_id.hex in bus.published[MT_ROUTE_PLAN][-1].replace("-", "")
