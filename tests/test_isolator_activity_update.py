"""Isolator: Activity-choice MA_FlightCommand UPDATE."""

from __future__ import annotations

from uuid import uuid4

import pytest

from open_vi.asb import InMemoryAsb
from open_vi.codec.command import (
    build_sample_activity_update_command,
    build_sample_waypoint_command,
    parse_flight_commands,
)
from open_vi.codec.mts import (
    MT_FLIGHT_ACTIVITY,
    MT_FLIGHT_COMMAND,
    MT_FLIGHT_COMMAND_STATUS,
    MT_MA_TASK,
)
from open_vi.codec.xmlutil import find_text, local_name, parse_xml
from open_vi.config import IsolatorConfig
from open_vi.domain import Waypoint
from open_vi.identity import SystemIdentity
from open_vi.isolator import Isolator
from open_vi.platform import StubPlatform


def _isolator() -> tuple[InMemoryAsb, StubPlatform, Isolator]:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(tick_republish_status=False),
    )
    iso.attach()
    return bus, platform, iso


def _start_waypoint(bus: InMemoryAsb, iso: Isolator):
    command_id = uuid4()
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_waypoint_command(
            iso.identity,
            command_id=command_id,
            capability_id=iso.ctx.state.capability_id,
        ),
    )
    return command_id


def test_parse_sample_activity_update_command() -> None:
    identity = SystemIdentity.named("1")
    command_id = uuid4()
    activity_id = uuid4()
    waypoints = (
        Waypoint(10.0, 20.0, 50.0),
        Waypoint(11.0, 21.0, 60.0),
    )
    xml = build_sample_activity_update_command(
        identity,
        command_id=command_id,
        activity_id=activity_id,
        waypoints=waypoints,
    )
    cmds = parse_flight_commands(xml)
    assert len(cmds) == 1
    assert cmds[0].choice == "Activity"
    assert cmds[0].command_state == "UPDATE"
    assert cmds[0].command_id == command_id
    assert cmds[0].activity_id == activity_id
    assert cmds[0].mode == "WAYPOINT_FOLLOWING"
    assert len(cmds[0].waypoints) == 2
    assert cmds[0].waypoints[0].latitude_deg == pytest.approx(10.0)


def test_activity_update_keeps_activity_id() -> None:
    bus, platform, iso = _isolator()
    _start_waypoint(bus, iso)
    live = iso.ctx.flight.activity_id
    assert live is not None
    first_activity = bus.published[MT_FLIGHT_ACTIVITY][-1]
    assert find_text(parse_xml(first_activity), "ObjectState") == "NEW"

    update_id = uuid4()
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_activity_update_command(
            iso.identity,
            command_id=update_id,
            activity_id=live,
            waypoints=(Waypoint(12.0, 22.0, 70.0),),
        ),
    )
    status = parse_xml(bus.published[MT_FLIGHT_COMMAND_STATUS][-1])
    assert local_name(status) == "MA_FlightCommandStatus"
    assert find_text(status, "CommandProcessingState") == "ACCEPTED"
    assert find_text(status, "NewActivity") == "false"
    assert live.hex in bus.published[MT_FLIGHT_COMMAND_STATUS][-1].replace(
        "-", ""
    )

    activity = parse_xml(bus.published[MT_FLIGHT_ACTIVITY][-1])
    assert find_text(activity, "ObjectState") == "UPDATED"
    assert iso.ctx.flight.activity_id == live
    snap = platform.active_flight_activity()
    assert snap is not None
    assert snap.activity_id == live


def test_activity_update_unknown_id_rejected() -> None:
    bus, _platform, iso = _isolator()
    _start_waypoint(bus, iso)
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_activity_update_command(
            iso.identity,
            command_id=uuid4(),
            activity_id=uuid4(),
        ),
    )
    status = bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert "REJECTED" in status
    assert "Unknown or idle ActivityID" in status
    assert local_name(parse_xml(bus.published[MT_MA_TASK][-1])) == "MA_Task"


def test_activity_update_idle_rejected() -> None:
    bus, _platform, iso = _isolator()
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_activity_update_command(
            iso.identity,
            command_id=uuid4(),
            activity_id=uuid4(),
        ),
    )
    status = bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert "REJECTED" in status
    assert "Unknown or idle ActivityID" in status
    assert MT_MA_TASK in bus.published


def test_activity_new_rejected() -> None:
    bus, _platform, iso = _isolator()
    _start_waypoint(bus, iso)
    live = iso.ctx.flight.activity_id
    assert live is not None
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_activity_update_command(
            iso.identity,
            command_id=uuid4(),
            activity_id=live,
            command_state="NEW",
        ),
    )
    status = bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert "REJECTED" in status
    assert "CommandState UPDATE" in status
    assert MT_MA_TASK in bus.published


def test_activity_cancel_rejected() -> None:
    bus, _platform, iso = _isolator()
    _start_waypoint(bus, iso)
    live = iso.ctx.flight.activity_id
    assert live is not None
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_activity_update_command(
            iso.identity,
            command_id=uuid4(),
            activity_id=live,
            command_state="CANCEL",
        ),
    )
    status = bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert "REJECTED" in status
    assert "CommandState UPDATE" in status
    assert MT_MA_TASK in bus.published


def test_capability_new_while_live_rejected() -> None:
    bus, _platform, iso = _isolator()
    _start_waypoint(bus, iso)
    live = iso.ctx.flight.activity_id
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_waypoint_command(
            iso.identity,
            command_id=uuid4(),
            capability_id=iso.ctx.state.capability_id,
        ),
    )
    status = bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert "REJECTED" in status
    assert "Activity UPDATE" in status
    assert iso.ctx.flight.activity_id == live
    assert MT_MA_TASK in bus.published


def test_capability_update_rejected() -> None:
    bus, _platform, iso = _isolator()
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_waypoint_command(
            iso.identity,
            command_id=uuid4(),
            capability_id=iso.ctx.state.capability_id,
            command_state="UPDATE",
        ),
    )
    status = bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert "REJECTED" in status
    assert "NEW or CANCEL" in status
    assert MT_MA_TASK in bus.published


def test_capability_new_after_completed_accepted() -> None:
    bus, platform, iso = _isolator()
    first = _start_waypoint(bus, iso)
    first_activity = iso.ctx.flight.activity_id
    assert platform.complete_flight_command(first) == first
    iso.publish_command_updates_once()
    assert iso.ctx.flight.activity_id is None
    second = uuid4()
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_waypoint_command(
            iso.identity,
            command_id=second,
            capability_id=iso.ctx.state.capability_id,
        ),
    )
    status = parse_xml(bus.published[MT_FLIGHT_COMMAND_STATUS][-1])
    assert find_text(status, "CommandProcessingState") == "ACCEPTED"
    assert find_text(status, "NewActivity") == "true"
    assert iso.ctx.flight.activity_id is not None
    assert iso.ctx.flight.activity_id != first_activity


def test_capability_cancel_after_new_still_works() -> None:
    bus, platform, iso = _isolator()
    command_id = _start_waypoint(bus, iso)
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_waypoint_command(
            iso.identity,
            command_id=command_id,
            capability_id=iso.ctx.state.capability_id,
            command_state="CANCEL",
        ),
    )
    assert "CANCELED" in bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert platform.active_flight_activity() is None
    assert platform.complete_flight_command(command_id) is None
