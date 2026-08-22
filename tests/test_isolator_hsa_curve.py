"""Isolator: HSA_CSA + CurveFollowing FlightCommand cycles."""

from __future__ import annotations

from uuid import uuid4

import pytest

from open_vi.asb import InMemoryAsb
from open_vi.codec.command import (
    build_sample_curve_following_command,
    build_sample_hsa_csa_command,
    parse_flight_commands,
)
from open_vi.codec.mts import (
    MT_FLIGHT_ACTIVITY,
    MT_FLIGHT_COMMAND,
    MT_FLIGHT_COMMAND_STATUS,
)
from open_vi.codec.xmlutil import local_name, parse_xml
from open_vi.config import IsolatorConfig
from open_vi.identity import SystemIdentity
from open_vi.isolator import Isolator
from open_vi.platform import StubPlatform


def test_parse_hsa_csa_command() -> None:
    identity = SystemIdentity.named("1")
    command_id = uuid4()
    capability_id = uuid4()
    xml = build_sample_hsa_csa_command(
        identity, command_id=command_id, capability_id=capability_id
    )
    cmds = parse_flight_commands(xml)
    assert len(cmds) == 1
    assert cmds[0].mode == "HSA_CSA"
    assert cmds[0].command_id == command_id
    assert cmds[0].hsa is not None
    assert cmds[0].hsa.heading_deg == pytest.approx(90.0)
    assert cmds[0].hsa.speed_mps == pytest.approx(5.0)
    assert cmds[0].hsa.altitude_m == pytest.approx(50.0)


def test_parse_curve_following_command() -> None:
    identity = SystemIdentity.named("1")
    command_id = uuid4()
    capability_id = uuid4()
    xml = build_sample_curve_following_command(
        identity, command_id=command_id, capability_id=capability_id
    )
    cmds = parse_flight_commands(xml)
    assert len(cmds) == 1
    assert cmds[0].mode == "CURVE_FOLLOWING"
    assert "CurveSegments" in (xml.decode() if isinstance(xml, bytes) else xml)


def test_hsa_csa_accepted() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(
            tick_republish_status=False, publish_vehicle_state=False
        ),
    )
    iso.attach()
    command_id = uuid4()
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_hsa_csa_command(
            iso.identity,
            command_id=command_id,
            capability_id=iso.ctx.state.capability_id,
        ),
    )
    status = bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert local_name(parse_xml(status)) == "MA_FlightCommandStatus"
    assert "ACCEPTED" in status
    assert command_id.hex in status.replace("-", "")
    activity = bus.published[MT_FLIGHT_ACTIVITY][-1]
    assert "ACTIVE_UNCONSTRAINED" in activity
    assert platform.active_flight_activity() is not None


def test_curve_following_accepted() -> None:
    bus = InMemoryAsb()
    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(
            tick_republish_status=False, publish_vehicle_state=False
        ),
    )
    iso.attach()
    command_id = uuid4()
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_curve_following_command(
            iso.identity,
            command_id=command_id,
            capability_id=iso.ctx.state.capability_id,
        ),
    )
    status = bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert "ACCEPTED" in status
    assert command_id.hex in status.replace("-", "")
    assert "ACTIVE_UNCONSTRAINED" in bus.published[MT_FLIGHT_ACTIVITY][-1]
