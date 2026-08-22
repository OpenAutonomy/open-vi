"""Parse MA_RoutePlan Path waypoints (shared with FlightCommand)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.route import (
    build_mission_plan_activation_status,
    build_sample_route_plan,
    build_sample_route_validation_command,
    parse_route_plan_waypoints,
    parse_route_validation_command,
    weather_blocks_route,
)
from open_vi.codec.xmlutil import (
    el,
    id_type,
    local_name,
    message_envelope,
    parse_xml,
    tostring,
)
from open_vi.domain import Waypoint
from open_vi.identity import SystemIdentity

FIXTURES = Path(__file__).parent / "fixtures"
GOLDEN_WAYPOINTS = (
    (47.3980, 8.5460, 30.0),
    (47.3985, 8.5465, 30.0),
    (47.3990, 8.5460, 30.0),
)


def test_parse_sample_route_plan_waypoints() -> None:
    identity = SystemIdentity.named("1")
    route_id = uuid4()
    waypoints = (
        Waypoint(10.0, 20.0, 50.0),
        Waypoint(11.0, 21.0, 60.0),
    )
    xml = build_sample_route_plan(
        identity, route_plan_id=route_id, waypoints=waypoints
    )
    parsed = parse_route_plan_waypoints(xml)
    assert len(parsed) == 2
    assert parsed[0].latitude_deg == pytest.approx(10.0)
    assert parsed[0].longitude_deg == pytest.approx(20.0)
    assert parsed[0].altitude_m == pytest.approx(50.0)
    assert parsed[1].latitude_deg == pytest.approx(11.0)


def test_parse_empty_route_plan_waypoints() -> None:
    identity = SystemIdentity.named("1")
    xml = build_sample_route_plan(identity, route_plan_id=uuid4(), waypoints=())
    assert parse_route_plan_waypoints(xml) == ()


def test_parse_opaque_route_plan_waypoints() -> None:
    assert parse_route_plan_waypoints("<rp/>") == ()


def test_parse_follows_path_segment_links() -> None:
    golden = parse_xml((FIXTURES / "MA_FlightCommand.xml").read_bytes())
    path = next(n for n in golden.iter() if local_name(n) == "Path")
    segs = [c for c in list(path) if local_name(c) == "PathSegment"]
    for seg in segs:
        path.remove(seg)
    for seg in reversed(segs):
        path.append(seg)
    identity = SystemIdentity.named("1")
    data = el("MessageData", id_type("RoutePlanID", uuid4()), path)
    root = message_envelope(
        "MA_RoutePlan",
        identity,
        data,
        schema_version=SCHEMA_VERSION,
        mode="SIMULATION",
        object_state="NEW",
    )
    parsed = parse_route_plan_waypoints(tostring(root))
    assert len(parsed) == 3
    for got, (lat, lon, alt) in zip(parsed, GOLDEN_WAYPOINTS, strict=True):
        assert got.latitude_deg == pytest.approx(lat, abs=1e-4)
        assert got.longitude_deg == pytest.approx(lon, abs=1e-4)
        assert got.altitude_m == pytest.approx(alt)


def test_build_mission_plan_activation_status() -> None:
    identity = SystemIdentity.named("1")
    mission_id = uuid4()
    route_id = uuid4()
    xml = build_mission_plan_activation_status(
        identity,
        mission_plan_id=mission_id,
        plan_activation_state="DEACTIVATED",
        route_plan_id=route_id,
    )
    root = parse_xml(xml)
    assert local_name(root) == "MissionPlanActivationStatus"
    body = xml.decode("utf-8")
    assert "DEACTIVATED" in body
    assert mission_id.hex in body.replace("-", "")
    assert route_id.hex in body.replace("-", "")
    assert "SubPlanActivationState" in body


def test_parse_validation_weather_area() -> None:
    identity = SystemIdentity.named("1")
    route_id = uuid4()
    xml = build_sample_route_validation_command(
        identity,
        command_id=uuid4(),
        route_plan_id=route_id,
        weather_source="OTHER",
        icing="SEVERE",
    )
    cmd = parse_route_validation_command(xml)
    assert cmd is not None
    assert cmd.weather is not None
    assert cmd.weather.source == "OTHER"
    assert cmd.weather.icing == "SEVERE"
    assert weather_blocks_route(cmd.weather)
    assert not weather_blocks_route(None)
