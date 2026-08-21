"""Isolator: contingencies + remaining Loose status package."""

from __future__ import annotations

from uuid import uuid4

from isolator_helpers import attach_isolator
from open_vi.asb import InMemoryAsb
from open_vi.codec.mts import (
    MT_CONTROL_STATUS,
    MT_FLIGHT_CAPABILITY,
    MT_FLIGHT_CAPABILITY_STATUS,
    MT_MA_FAULT,
    MT_MA_RESPONSE,
    MT_QUERY_DATA_REQUEST,
    MT_QUERY_DATA_REQUEST_STATUS,
    MT_RESPONSE_PLAN_EXECUTION_STATUS,
    MT_ROUTE_PLAN_EXECUTION_STATUS,
    MT_SUBSYSTEM_STATUS,
    MT_SYSTEM_MGMT_REQUEST,
    MT_SYSTEM_MGMT_STATUS,
    MT_SYSTEM_NOTIFICATION,
)
from open_vi.codec.notification import build_sample_ma_response
from open_vi.codec.query import build_sample_query_data_request
from open_vi.codec.system_mgmt import build_sample_system_management_request
from open_vi.codec.xmlutil import local_name, parse_xml
from open_vi.config import IsolatorConfig
from open_vi.isolator import Isolator
from open_vi.platform import StubPlatform


def _iso(bus: InMemoryAsb, platform: StubPlatform | None = None) -> Isolator:
    return Isolator(
        bus,
        platform=platform or StubPlatform(),
        config=IsolatorConfig(
            tick_republish_status=False,
            publish_vehicle_state=False,
            publish_status_package=False,
        ),
    )


def test_mechanical_damage_publishes_fault() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = _iso(bus, platform)
    attach_isolator(iso)
    platform.inject_contingency("MECHANICAL_DAMAGE")
    iso.publish_faults_once()
    assert len(bus.published[MT_MA_FAULT]) == 1
    fault = bus.published[MT_MA_FAULT][-1]
    assert local_name(parse_xml(fault)) == "MA_Fault"
    assert "MECHANICAL_DAMAGE" in fault
    assert "SET" in fault


def test_sensor_failure_publishes_subsystem_then_fault() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = _iso(bus, platform)
    attach_isolator(iso)
    platform.inject_contingency("SENSOR_FAILURE")
    iso.publish_subsystem_status_once()
    iso.publish_faults_once()
    assert len(bus.published[MT_SUBSYSTEM_STATUS]) == 1
    assert "DEGRADED" in bus.published[MT_SUBSYSTEM_STATUS][-1]
    assert len(bus.published[MT_MA_FAULT]) == 1
    assert "SENSOR_FAILURE" in bus.published[MT_MA_FAULT][-1]


def test_collision_avoidance_status_then_capability() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = _iso(bus, platform)
    attach_isolator(iso)
    platform.inject_contingency("COLLISION_AVOIDANCE")
    iso.publish_capability_status_once()
    iso.publish_flight_capability_once()
    assert len(bus.published[MT_FLIGHT_CAPABILITY_STATUS]) == 1
    status = bus.published[MT_FLIGHT_CAPABILITY_STATUS][-1]
    assert "UNAVAILABLE" in status
    assert "CONSTRAINT_COLLISION_AVOIDANCE" in status
    assert len(bus.published[MT_FLIGHT_CAPABILITY]) == 1
    assert local_name(parse_xml(bus.published[MT_FLIGHT_CAPABILITY][-1])) == (
        "MA_FlightCapability"
    )


def test_ma_failsafe_response_yields_notification() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    attach_isolator(iso)
    response_id = uuid4()
    bus.publish(
        MT_MA_RESPONSE,
        build_sample_ma_response(iso.identity, response_id=response_id),
    )
    assert len(bus.published[MT_SYSTEM_NOTIFICATION]) == 1
    note = bus.published[MT_SYSTEM_NOTIFICATION][-1]
    assert "CONFIRMED" in note
    assert "MA_RESPONSE" in note
    assert response_id.hex in note.replace("-", "")


def test_publish_status_package() -> None:
    bus = InMemoryAsb()
    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(
            tick_republish_status=False,
            publish_vehicle_state=False,
            publish_status_package=True,
        ),
    )
    bus.connect()
    iso.advertise_once()
    iso.publish_status_package_once()
    assert len(bus.published[MT_CONTROL_STATUS]) == 1
    assert "CAPABILITY_COMMAND" in bus.published[MT_CONTROL_STATUS][-1]
    assert len(bus.published[MT_RESPONSE_PLAN_EXECUTION_STATUS]) == 1
    idle = bus.published[MT_RESPONSE_PLAN_EXECUTION_STATUS][-1]
    assert "ACTUAL" in idle
    assert "EXECUTING" not in idle
    assert MT_ROUTE_PLAN_EXECUTION_STATUS not in bus.published
    assert len(bus.published[MT_SUBSYSTEM_STATUS]) == 1


def test_barometric_system_management_completed() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = _iso(bus, platform)
    attach_isolator(iso)
    request_id = uuid4()
    bus.publish(
        MT_SYSTEM_MGMT_REQUEST,
        build_sample_system_management_request(
            iso.identity, request_id=request_id, qnh_kpa=101.325
        ),
    )
    assert len(bus.published[MT_SYSTEM_MGMT_STATUS]) == 1
    status = bus.published[MT_SYSTEM_MGMT_STATUS][-1]
    assert "COMPLETED" in status
    assert request_id.hex in status.replace("-", "")
    assert abs(platform.get_vehicle_state().kollsman_hpa - 1013.25) < 0.01


def test_query_data_request_statuses() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    attach_isolator(iso)
    request_id = uuid4()
    bus.publish(
        MT_QUERY_DATA_REQUEST,
        build_sample_query_data_request(iso.identity, request_id=request_id),
    )
    statuses = list(bus.published[MT_QUERY_DATA_REQUEST_STATUS])
    assert len(statuses) == 3
    assert "QUEUED" in statuses[0]
    assert "PROCESSING" in statuses[1]
    assert "COMPLETED" in statuses[2]
    assert request_id.hex in statuses[2].replace("-", "")
