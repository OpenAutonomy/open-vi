"""Isolator: QUEUED → PROCESSING → COMPLETED on route and query."""

from __future__ import annotations

from uuid import uuid4

from open_vi.asb import InMemoryAsb
from open_vi.codec.mts import (
    MT_ACTIVATION_COMMAND,
    MT_ACTIVATION_STATUS,
    MT_MISSION_PLAN_ACTIVATION_STATUS,
    MT_QUERY_DATA_REQUEST,
    MT_QUERY_DATA_REQUEST_STATUS,
)
from open_vi.codec.query import build_sample_query_data_request
from open_vi.codec.route import build_sample_route_activation_command
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


def test_route_activation_three_statuses() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    bus.publish(
        MT_ACTIVATION_COMMAND,
        build_sample_route_activation_command(
            iso.identity,
            command_id=uuid4(),
            mission_plan_id=uuid4(),
            route_plan_id=uuid4(),
            command_type="PREPARE_FOR_UPLOAD",
        ),
    )
    statuses = list(bus.published[MT_ACTIVATION_STATUS])
    assert len(statuses) == 3
    assert "QUEUED" in statuses[0]
    assert "PROCESSING" in statuses[1]
    assert "COMPLETED" in statuses[2]
    assert "READY_FOR_UPLOAD" in statuses[2]


def test_route_deactivate_single_status() -> None:
    bus = InMemoryAsb()
    route_id = uuid4()
    mission_id = uuid4()
    iso = _iso(bus)
    iso.ctx.routes.prime(
        route_id, mission_plan_id=mission_id, state="ACTIVATED", xml="<rp/>"
    )
    iso.attach()
    bus.publish(
        MT_ACTIVATION_COMMAND,
        build_sample_route_activation_command(
            iso.identity,
            command_id=uuid4(),
            mission_plan_id=mission_id,
            route_plan_id=route_id,
            command_type="DEACTIVATE",
        ),
    )
    assert len(bus.published[MT_ACTIVATION_STATUS]) == 1
    assert "COMPLETED" in bus.published[MT_ACTIVATION_STATUS][0]
    assert len(bus.published[MT_MISSION_PLAN_ACTIVATION_STATUS]) == 1
    assert "DEACTIVATED" in bus.published[MT_MISSION_PLAN_ACTIVATION_STATUS][0]


def test_query_three_statuses() -> None:
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
