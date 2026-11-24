"""Build → parse fidelity for every codec pair that has both sides.

The codec is not an XSD binding, so nothing structural guarantees that
what it writes is what it reads. These tests close the loop: build a
message from known values, parse it back, and assert the values
survived. A builder that emits a field the parser looks for under a
different name passes every other test in the suite and fails here.
"""

from __future__ import annotations

import math
from uuid import UUID

import pytest

from open_vi.codec.capability import (
    build_flight_capability,
    parse_flight_capability,
)
from open_vi.codec.command import (
    build_sample_curve_following_command,
    build_sample_hsa_csa_command,
    build_sample_waypoint_command,
    parse_flight_commands,
)
from open_vi.codec.control import (
    build_sample_control_request,
    parse_control_request,
)
from open_vi.codec.notification import (
    build_sample_ma_response,
    parse_ma_response,
    parse_response_id,
)
from open_vi.codec.query import (
    build_sample_query_data_request,
    parse_query_request,
)
from open_vi.codec.route import (
    build_sample_route_activation_command,
    build_sample_route_plan,
    build_sample_route_validation_command,
    parse_route_activation_commands,
    parse_route_plan_id,
    parse_route_plan_waypoints,
    parse_route_validation_command,
)
from open_vi.codec.status import build_sample_service_status, parse_service_id
from open_vi.codec.system_mgmt import (
    build_sample_system_management_request,
    parse_qnh_setting_kpa,
)
from open_vi.codec.task import (
    build_ma_task,
    build_sample_task_command,
    parse_ma_task,
    parse_task_commands,
)
from open_vi.codec.xmlutil import parse_header_system_id
from open_vi.domain import ControlOffer, Waypoint
from open_vi.identity import SystemIdentity

IDENTITY = SystemIdentity.named("open-vi", "open-vi")
CMD = UUID(int=0xC1)
CAP = UUID(int=0xC0)
ROUTE = UUID(int=0xB0)
MISSION = UUID(int=0xB1)
REQ = UUID(int=0xA1)
TASK = UUID(int=0xA2)
RESP = UUID(int=0xA3)
SERVICE = UUID(int=0x51)

WAYPOINTS = (
    Waypoint(latitude_deg=38.5, longitude_deg=-77.25, altitude_m=120.0),
    Waypoint(latitude_deg=38.75, longitude_deg=-77.5, altitude_m=140.0),
)


def _all_messages() -> list[tuple[str, bytes]]:
    """One of every inbound-shaped message, for the header check."""
    return [
        (
            "waypoint",
            build_sample_waypoint_command(
                IDENTITY, command_id=CMD, capability_id=CAP
            ),
        ),
        (
            "hsa",
            build_sample_hsa_csa_command(
                IDENTITY, command_id=CMD, capability_id=CAP
            ),
        ),
        (
            "curve",
            build_sample_curve_following_command(
                IDENTITY, command_id=CMD, capability_id=CAP
            ),
        ),
        ("route_plan", build_sample_route_plan(IDENTITY, route_plan_id=ROUTE)),
        (
            "activation",
            build_sample_route_activation_command(
                IDENTITY,
                command_id=CMD,
                mission_plan_id=MISSION,
                route_plan_id=ROUTE,
                command_type="ACTIVATE",
            ),
        ),
        (
            "validation",
            build_sample_route_validation_command(
                IDENTITY, command_id=CMD, route_plan_id=ROUTE
            ),
        ),
        (
            "control",
            build_sample_control_request(IDENTITY, request_id=REQ),
        ),
        (
            "task_command",
            build_sample_task_command(
                IDENTITY, command_id=CMD, task_id=TASK, capability_id=CAP
            ),
        ),
        ("ma_task", build_ma_task(IDENTITY, task_id=TASK)),
        ("ma_response", build_sample_ma_response(IDENTITY, response_id=RESP)),
        (
            "query",
            build_sample_query_data_request(IDENTITY, request_id=REQ),
        ),
        (
            "sysmgmt",
            build_sample_system_management_request(IDENTITY, request_id=REQ),
        ),
        (
            "service_status",
            build_sample_service_status(IDENTITY, service_id=SERVICE),
        ),
        (
            "capability",
            build_flight_capability(
                IDENTITY, ControlOffer(), capability_id=CAP
            ),
        ),
    ]


@pytest.mark.parametrize("label,xml", _all_messages(), ids=lambda v: v)
def test_header_system_id_round_trips(label: str, xml: bytes) -> None:
    """Every message carries a recoverable MessageHeader/SystemID."""
    del label
    assert parse_header_system_id(xml) == IDENTITY.uuid


def test_waypoint_command_round_trips() -> None:
    xml = build_sample_waypoint_command(
        IDENTITY, command_id=CMD, capability_id=CAP, waypoints=WAYPOINTS
    )
    (req,) = parse_flight_commands(xml)
    assert req.command_id == CMD
    assert req.capability_id == CAP
    assert req.command_state == "NEW"
    assert req.mode == "WAYPOINT_FOLLOWING"
    assert len(req.waypoints) == len(WAYPOINTS)
    for got, want in zip(req.waypoints, WAYPOINTS, strict=True):
        # Degrees in domain, radians on the wire: allow float noise.
        assert math.isclose(got.latitude_deg, want.latitude_deg, abs_tol=1e-6)
        assert math.isclose(got.longitude_deg, want.longitude_deg, abs_tol=1e-6)
        assert got.altitude_m is not None
        assert math.isclose(got.altitude_m, want.altitude_m, abs_tol=1e-6)


def test_hsa_csa_command_round_trips() -> None:
    xml = build_sample_hsa_csa_command(
        IDENTITY,
        command_id=CMD,
        capability_id=CAP,
        heading_deg=135.0,
        speed_mps=22.5,
        altitude_m=175.0,
    )
    (req,) = parse_flight_commands(xml)
    assert req.mode == "HSA_CSA"
    assert req.hsa is not None
    assert math.isclose(req.hsa.heading_deg, 135.0, abs_tol=1e-6)
    assert math.isclose(req.hsa.speed_mps, 22.5, abs_tol=1e-6)
    assert math.isclose(req.hsa.altitude_m, 175.0, abs_tol=1e-6)


def test_curve_following_command_round_trips() -> None:
    xml = build_sample_curve_following_command(
        IDENTITY, command_id=CMD, capability_id=CAP
    )
    (req,) = parse_flight_commands(xml)
    assert req.mode == "CURVE_FOLLOWING"
    assert req.curve is not None
    assert req.curve.control_points


def test_route_plan_round_trips() -> None:
    xml = build_sample_route_plan(
        IDENTITY, route_plan_id=ROUTE, waypoints=WAYPOINTS
    )
    assert parse_route_plan_id(xml) == ROUTE
    parsed = parse_route_plan_waypoints(xml)
    assert len(parsed) == len(WAYPOINTS)
    for got, want in zip(parsed, WAYPOINTS, strict=True):
        assert math.isclose(got.latitude_deg, want.latitude_deg, abs_tol=1e-6)


@pytest.mark.parametrize(
    "command_type",
    ["PREPARE_FOR_UPLOAD", "UPLOAD", "PREPARE_FOR_ACTIVATION", "ACTIVATE"],
)
def test_route_activation_round_trips(command_type: str) -> None:
    xml = build_sample_route_activation_command(
        IDENTITY,
        command_id=CMD,
        mission_plan_id=MISSION,
        route_plan_id=ROUTE,
        command_type=command_type,
    )
    (req,) = parse_route_activation_commands(xml)
    assert req.command_id == CMD
    assert req.route_plan_id == ROUTE
    assert req.mission_plan_id == MISSION
    assert req.command_type == command_type


def test_route_validation_round_trips() -> None:
    xml = build_sample_route_validation_command(
        IDENTITY, command_id=CMD, route_plan_id=ROUTE
    )
    parsed = parse_route_validation_command(xml)
    assert parsed is not None
    assert parsed.command_id == CMD
    assert parsed.route_plan_id == ROUTE


@pytest.mark.parametrize("request_type", ["ACQUIRE", "STEAL", "RELEASE"])
def test_control_request_round_trips(request_type: str) -> None:
    xml = build_sample_control_request(
        IDENTITY, request_id=REQ, request_type=request_type
    )
    parsed = parse_control_request(xml)
    assert parsed is not None
    assert parsed.request_id == REQ
    assert parsed.request_type == request_type


def test_task_command_round_trips() -> None:
    xml = build_sample_task_command(
        IDENTITY, command_id=CMD, task_id=TASK, capability_id=CAP
    )
    (req,) = parse_task_commands(xml)
    assert req.command_id == CMD
    assert req.task_id == TASK


def test_ma_task_round_trips() -> None:
    parsed = parse_ma_task(build_ma_task(IDENTITY, task_id=TASK))
    assert parsed is not None
    assert parsed.task_id == TASK


def test_ma_response_round_trips() -> None:
    xml = build_sample_ma_response(
        IDENTITY, response_id=RESP, route_plan_id=ROUTE
    )
    assert parse_response_id(xml) == RESP
    parsed = parse_ma_response(xml)
    assert parsed is not None
    assert parsed.response_id == RESP


@pytest.mark.parametrize(
    "message_types,expected",
    [
        (("MA_FLIGHT_CAPABILITY",), ("capability",)),
        (("MA_ROUTE_PLAN",), ("route",)),
        (("AIRFIELD_REPORT",), ("airfield",)),
        (
            ("MA_FLIGHT_CAPABILITY", "MA_ROUTE_PLAN", "AIRFIELD_REPORT"),
            ("capability", "route", "airfield"),
        ),
    ],
)
def test_query_request_round_trips(
    message_types: tuple[str, ...], expected: tuple[str, ...]
) -> None:
    xml = build_sample_query_data_request(
        IDENTITY, request_id=REQ, message_types=message_types
    )
    parsed = parse_query_request(xml)
    assert parsed.kinds == expected
    assert parsed.identifiers_only is False


def test_query_identifiers_only_round_trips() -> None:
    xml = build_sample_query_data_request(
        IDENTITY, request_id=REQ, identifiers_only=True
    )
    assert parse_query_request(xml).identifiers_only is True


@pytest.mark.parametrize("qnh", [101.325, 99.5, 103.0])
def test_qnh_round_trips(qnh: float) -> None:
    xml = build_sample_system_management_request(
        IDENTITY, request_id=REQ, qnh_kpa=qnh
    )
    parsed = parse_qnh_setting_kpa(xml)
    assert parsed is not None
    assert math.isclose(parsed, qnh, abs_tol=1e-6)


def test_service_status_round_trips() -> None:
    xml = build_sample_service_status(IDENTITY, service_id=SERVICE)
    assert parse_service_id(xml) == SERVICE


def test_flight_capability_round_trips() -> None:
    offer = ControlOffer(
        capability_types=("HSA_CSA", "WAYPOINT_FOLLOWING"),
        accepted_interfaces=("CAPABILITY_COMMAND",),
    )
    xml = build_flight_capability(IDENTITY, offer, capability_id=CAP)
    parsed = parse_flight_capability(xml)
    assert parsed is not None
    assert set(parsed.capability_types) == set(offer.capability_types)
