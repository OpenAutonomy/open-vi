"""Isolator: QueryDataRequest native outs by MessageType."""

from __future__ import annotations

from uuid import uuid4

from open_vi.asb import InMemoryAsb
from open_vi.codec.mts import (
    MT_AIRFIELD_REPORT,
    MT_FILE_LOCATION,
    MT_FILE_METADATA,
    MT_FLIGHT_CAPABILITY,
    MT_QUERY_DATA_REQUEST,
    MT_QUERY_DATA_REQUEST_STATUS,
    MT_ROUTE_PLAN,
)
from open_vi.codec.query import (
    build_sample_query_data_request,
    parse_query_kinds,
    parse_query_request,
)
from open_vi.codec.route import build_sample_route_plan
from open_vi.codec.xmlutil import local_name, parse_xml
from open_vi.config import IsolatorConfig
from open_vi.isolator import Isolator
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
    parsed = parse_query_request(
        build_sample_query_data_request(
            iso.identity,
            request_id=uuid4(),
            message_types=("MA_ROUTE_PLAN",),
            identifiers_only=True,
        )
    )
    assert parsed.kinds == ("route",)
    assert parsed.identifiers_only


def test_capability_query_republishes_flight_capability() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    bus.publish(
        MT_QUERY_DATA_REQUEST,
        build_sample_query_data_request(iso.identity, request_id=uuid4()),
    )
    assert len(bus.published[MT_QUERY_DATA_REQUEST_STATUS]) == 3
    cap = bus.published[MT_FLIGHT_CAPABILITY][-1]
    assert local_name(parse_xml(cap)) == "MA_FlightCapability"
    assert iso.ctx.state.capability_id.hex in cap.replace("-", "")
    assert MT_AIRFIELD_REPORT not in bus.published
    completed = bus.published[MT_QUERY_DATA_REQUEST_STATUS][-1]
    assert "Result" in completed
    assert iso.ctx.state.capability_id.hex in completed.replace("-", "")


def test_airfield_query_publishes_report() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    airfield = iso.ctx.airfield
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
    assert "Runway" in report
    assert "TakeoffCoordinates" in report
    assert "LandingCoordinates" in report
    assert airfield.runway_id.hex in report.replace("-", "")
    plans = list(bus.published[MT_ROUTE_PLAN])
    assert len(plans) == 2
    joined = "".join(plans)
    assert "TAKEOFF" in joined
    assert "LANDING" in joined
    assert airfield.airfield_id.hex in joined.replace("-", "")
    assert airfield.runway_id.hex in joined.replace("-", "")
    completed = bus.published[MT_QUERY_DATA_REQUEST_STATUS][-1]
    assert airfield.takeoff_route_id.hex in completed.replace("-", "")
    assert airfield.landing_route_id.hex in completed.replace("-", "")


def test_route_query_returns_file_star_and_plan() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
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
    ingested = len(iso.ctx.routes.ingested_ids())
    assert ingested == 3
    assert len(bus.published[MT_FILE_LOCATION]) == before_files + ingested
    assert len(bus.published[MT_FILE_METADATA]) == before_files + ingested
    plans = "".join(bus.published[MT_ROUTE_PLAN])
    assert route_id.hex in plans.replace("-", "")
    assert iso.ctx.airfield.takeoff_route_id.hex in plans.replace("-", "")


def test_identifiers_only_returns_result_ids() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    route_id = uuid4()
    bus.publish(
        MT_ROUTE_PLAN,
        build_sample_route_plan(iso.identity, route_plan_id=route_id),
    )
    before_files = len(bus.published[MT_FILE_LOCATION])
    before_plans = len(bus.published[MT_ROUTE_PLAN])
    bus.publish(
        MT_QUERY_DATA_REQUEST,
        build_sample_query_data_request(
            iso.identity,
            request_id=uuid4(),
            message_types=("MA_ROUTE_PLAN",),
            identifiers_only=True,
        ),
    )
    assert len(bus.published[MT_FILE_LOCATION]) == before_files
    assert len(bus.published[MT_ROUTE_PLAN]) == before_plans
    completed = bus.published[MT_QUERY_DATA_REQUEST_STATUS][-1]
    assert "COMPLETED" in completed
    assert "Result" in completed
    assert route_id.hex in completed.replace("-", "")


def test_route_query_includes_preloaded_tol() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    airfield = iso.ctx.airfield
    bus.publish(
        MT_QUERY_DATA_REQUEST,
        build_sample_query_data_request(
            iso.identity,
            request_id=uuid4(),
            message_types=("MA_ROUTE_PLAN",),
            identifiers_only=True,
        ),
    )
    completed = bus.published[MT_QUERY_DATA_REQUEST_STATUS][-1]
    assert "COMPLETED" in completed
    assert "Result" in completed
    assert airfield.takeoff_route_id.hex in completed.replace("-", "")
    assert airfield.landing_route_id.hex in completed.replace("-", "")
    assert MT_ROUTE_PLAN not in bus.published


def test_route_checksum_mismatch_fails_query() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    route_id = uuid4()
    bus.publish(
        MT_ROUTE_PLAN,
        build_sample_route_plan(iso.identity, route_plan_id=route_id),
    )
    iso.ctx.routes._routes[route_id].xml = "<tampered/>"
    before_files = len(bus.published[MT_FILE_LOCATION])
    bus.publish(
        MT_QUERY_DATA_REQUEST,
        build_sample_query_data_request(
            iso.identity,
            request_id=uuid4(),
            message_types=("MA_ROUTE_PLAN",),
        ),
    )
    statuses = list(bus.published[MT_QUERY_DATA_REQUEST_STATUS])
    assert "QUEUED" in statuses[0]
    assert "PROCESSING" in statuses[1]
    assert "FAILED" in statuses[2]
    assert "INVALID_INPUT_PARAMETER" in statuses[2]
    assert "checksum" in statuses[2].lower()
    assert len(bus.published[MT_FILE_LOCATION]) == before_files
