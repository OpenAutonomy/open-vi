"""Isolator: contingencies + remaining Loose status package."""

from __future__ import annotations

from uuid import uuid4

from open_vi.asb import InMemoryAsb
from open_vi.codec.mts import (
    MT_ACTIVATION_STATUS,
    MT_ACTIVITY_PLAN_EXECUTION_STATUS,
    MT_CONTROL_STATUS,
    MT_FLIGHT_ACTIVITY,
    MT_FLIGHT_CAPABILITY,
    MT_FLIGHT_CAPABILITY_STATUS,
    MT_MA_FAULT,
    MT_MA_RESPONSE,
    MT_MISSION_PLAN_EXECUTION_STATUS,
    MT_QUERY_DATA_REQUEST,
    MT_QUERY_DATA_REQUEST_STATUS,
    MT_RESPONSE_PLAN_EXECUTION_STATUS,
    MT_ROUTE_ACTIVITY_PLAN_EXECUTION_STATUS,
    MT_ROUTE_PLAN_EXECUTION_STATUS,
    MT_SUBSYSTEM_STATUS,
    MT_SYSTEM_MGMT_REQUEST,
    MT_SYSTEM_MGMT_STATUS,
    MT_SYSTEM_NOTIFICATION,
    MT_TASK_PLAN_EXECUTION_STATUS,
)
from open_vi.codec.notification import (
    build_sample_ma_response,
    parse_ma_response,
)
from open_vi.codec.query import build_sample_query_data_request
from open_vi.codec.route import build_sample_route_plan
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
    iso.attach()
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
    iso.attach()
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
    iso.attach()
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


def test_parse_ma_response_activate_plan() -> None:
    iso = _iso(InMemoryAsb())
    response_id = uuid4()
    route_id = uuid4()
    mission_id = uuid4()
    parsed = parse_ma_response(
        build_sample_ma_response(
            iso.identity,
            response_id=response_id,
            route_plan_id=route_id,
            mission_plan_id=mission_id,
        )
    )
    assert parsed is not None
    assert parsed.response_id == response_id
    assert parsed.route_plan_id == route_id
    assert parsed.mission_plan_id == mission_id
    assert parsed.object_state == "NEW"


def test_ma_failsafe_response_yields_notification() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
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
    assert iso.ctx.state.failsafe_response_id == response_id
    assert iso.ctx.state.failsafe_route_id is None
    assert MT_FLIGHT_ACTIVITY not in bus.published


def test_failsafe_activate_plan_flies_stored_route() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = _iso(bus, platform)
    iso.attach()
    route_id = uuid4()
    mission_id = uuid4()
    response_id = uuid4()
    plan = build_sample_route_plan(iso.identity, route_plan_id=route_id)
    iso.ctx.routes.ingest(
        route_id, plan.decode("utf-8"), mission_plan_id=mission_id
    )
    bus.publish(
        MT_MA_RESPONSE,
        build_sample_ma_response(
            iso.identity,
            response_id=response_id,
            route_plan_id=route_id,
            mission_plan_id=mission_id,
        ),
    )
    assert iso.ctx.state.failsafe_response_id == response_id
    assert iso.ctx.state.failsafe_route_id == route_id
    stored = iso.ctx.routes.get(route_id)
    assert stored is not None
    assert stored.plan_state == "ACTIVATED"
    activity = platform.active_flight_activity()
    assert activity is not None
    assert iso.ctx.flight.activity_id == activity.activity_id
    assert iso.ctx.execution.plan_id == route_id
    assert iso.ctx.execution.state == "EXECUTING"
    assert len(bus.published[MT_SYSTEM_NOTIFICATION]) == 1
    assert "MA_RESPONSE" in bus.published[MT_SYSTEM_NOTIFICATION][-1]
    assert len(bus.published[MT_FLIGHT_ACTIVITY]) == 1
    assert "EXECUTING" in bus.published[MT_RESPONSE_PLAN_EXECUTION_STATUS][-1]
    assert "EXECUTING" in bus.published[MT_ROUTE_PLAN_EXECUTION_STATUS][-1]
    assert "EXECUTING" in bus.published[MT_MISSION_PLAN_EXECUTION_STATUS][-1]
    assert MT_ACTIVATION_STATUS not in bus.published


def test_failsafe_activate_plan_missing_route_notifies_only() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    route_id = uuid4()
    response_id = uuid4()
    bus.publish(
        MT_MA_RESPONSE,
        build_sample_ma_response(
            iso.identity,
            response_id=response_id,
            route_plan_id=route_id,
        ),
    )
    assert iso.ctx.state.failsafe_response_id == response_id
    assert iso.ctx.state.failsafe_route_id == route_id
    assert len(bus.published[MT_SYSTEM_NOTIFICATION]) == 1
    assert MT_FLIGHT_ACTIVITY not in bus.published
    assert iso.ctx.execution.plan_id is None


def test_failsafe_removed_clears_store() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    route_id = uuid4()
    response_id = uuid4()
    bus.publish(
        MT_MA_RESPONSE,
        build_sample_ma_response(
            iso.identity,
            response_id=response_id,
            route_plan_id=route_id,
        ),
    )
    bus.publish(
        MT_MA_RESPONSE,
        build_sample_ma_response(
            iso.identity,
            response_id=response_id,
            route_plan_id=route_id,
            object_state="REMOVED",
        ),
    )
    assert iso.ctx.state.failsafe_response_id is None
    assert iso.ctx.state.failsafe_route_id is None
    assert len(bus.published[MT_SYSTEM_NOTIFICATION]) == 1


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
    assert "PrimaryController" in bus.published[MT_CONTROL_STATUS][-1]
    assert "SecondaryController" not in bus.published[MT_CONTROL_STATUS][-1]
    assert "MissionControl" in bus.published[MT_CONTROL_STATUS][-1]
    assert "InMission" in bus.published[MT_CONTROL_STATUS][-1]
    assert len(bus.published[MT_RESPONSE_PLAN_EXECUTION_STATUS]) == 1
    idle = bus.published[MT_RESPONSE_PLAN_EXECUTION_STATUS][-1]
    assert "ACTUAL" in idle
    assert "EXECUTING" not in idle
    assert MT_ROUTE_PLAN_EXECUTION_STATUS not in bus.published
    activity = bus.published[MT_ACTIVITY_PLAN_EXECUTION_STATUS][-1]
    assert local_name(parse_xml(activity)) == "ActivityPlanExecutionStatus"
    assert "ACTUAL" in activity
    assert "EXECUTING" not in activity
    route_activity = bus.published[MT_ROUTE_ACTIVITY_PLAN_EXECUTION_STATUS][-1]
    assert local_name(parse_xml(route_activity)) == (
        "RouteActivityPlanExecutionStatus"
    )
    assert "ACTUAL" in route_activity
    assert "EXECUTING" not in route_activity
    task_plan = bus.published[MT_TASK_PLAN_EXECUTION_STATUS][-1]
    assert local_name(parse_xml(task_plan)) == "TaskPlanExecutionStatus"
    assert "ACTUAL" in task_plan
    assert "EXECUTING" not in task_plan
    assert len(bus.published[MT_SUBSYSTEM_STATUS]) == 1
    assert len(bus.published[MT_MA_FAULT]) == 1
    assert local_name(parse_xml(bus.published[MT_MA_FAULT][-1])) == "MA_Fault"


def test_barometric_system_management_completed() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = _iso(bus, platform)
    iso.attach()
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
    iso.attach()
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
