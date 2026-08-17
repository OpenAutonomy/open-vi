"""Isolator: MA_FlightCommand → Status → Activity (WaypointFollowing)."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest

from isolator_helpers import attach_isolator
from open_vi.asb import InMemoryAsb
from open_vi.codec.command import (
    build_sample_waypoint_command,
    parse_flight_commands,
)
from open_vi.codec.geo import deg_to_rad, format_uci_angle, rad_to_deg
from open_vi.codec.xmlutil import (
    el,
    id_type,
    local_name,
    message_envelope,
    parse_xml,
    tostring,
)
from open_vi.config import IsolatorConfig
from open_vi.domain import ControlReadiness, Waypoint
from open_vi.identity import SystemIdentity
from open_vi.isolator import Isolator
from open_vi.isolator.handlers.flight_command import (
    MT_FLIGHT_ACTIVITY,
    MT_FLIGHT_COMMAND,
    MT_FLIGHT_COMMAND_STATUS,
)
from open_vi.isolator.handlers.task import MT_MA_TASK
from open_vi.platform import StubPlatform


def test_geo_angle_round_trip() -> None:
    assert rad_to_deg(deg_to_rad(38.8895)) == pytest.approx(38.8895)
    assert format_uci_angle(deg_to_rad(10.0)).startswith("0.174532")


def test_parse_sample_waypoint_command() -> None:
    identity = SystemIdentity.named("1")
    command_id = uuid4()
    capability_id = uuid4()
    xml = build_sample_waypoint_command(
        identity,
        command_id=command_id,
        capability_id=capability_id,
        waypoints=(
            Waypoint(10.0, 20.0, 50.0),
            Waypoint(11.0, 21.0, 60.0),
        ),
    )
    # Wire format is UCI radians, not degrees.
    assert b"0.174532" in xml
    cmds = parse_flight_commands(xml)
    assert len(cmds) == 1
    assert cmds[0].command_id == command_id
    assert cmds[0].capability_id == capability_id
    assert cmds[0].mode == "WAYPOINT_FOLLOWING"
    assert cmds[0].command_state == "NEW"
    assert len(cmds[0].waypoints) == 2
    assert cmds[0].waypoints[0].latitude_deg == pytest.approx(10.0)
    assert cmds[0].waypoints[0].longitude_deg == pytest.approx(20.0)
    assert cmds[0].waypoints[1].latitude_deg == pytest.approx(11.0)


def test_waypoint_command_accepted_publishes_status_and_activity() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(tick_republish_status=False),
    )
    attach_isolator(iso)
    iso.advertise_once()

    command_id = uuid4()
    xml = build_sample_waypoint_command(
        iso.identity,
        command_id=command_id,
        capability_id=iso.ctx.state.capability_id,
    )
    bus.publish(MT_FLIGHT_COMMAND, xml)

    status = bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert local_name(parse_xml(status)) == "MA_FlightCommandStatus"
    assert "ACCEPTED" in status
    assert command_id.hex in status.replace("-", "")

    activity = bus.published[MT_FLIGHT_ACTIVITY][-1]
    assert local_name(parse_xml(activity)) == "MA_FlightActivity"
    assert "ACTIVE_UNCONSTRAINED" in activity
    assert "VehicleCommandState" in activity
    assert iso.ctx.state.active_activity_id is not None
    assert platform.active_flight_activity() is not None


def test_unknown_control_mode_rejected() -> None:
    bus = InMemoryAsb()
    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(tick_republish_status=False),
    )
    attach_isolator(iso)

    # Capability command with no FlightControlMode → mode None → reject.
    identity = iso.identity
    command_id = UUID(int=42)
    capability = el(
        "Capability",
        id_type("CommandID", command_id),
        el("CommandState", text="NEW"),
        id_type("CapabilityID", iso.ctx.state.capability_id),
        el(
            "Ranking",
            el(
                "Rank",
                el("Priority", text="0"),
                el("PrecedenceWithinPriority", text="0"),
            ),
        ),
    )
    root = message_envelope(
        "MA_FlightCommand",
        identity,
        el("MessageData", el("Command", capability)),
        schema_version=iso.ctx.schema_version,
        mode=iso.ctx.message_mode,
    )
    bus.publish(MT_FLIGHT_COMMAND, tostring(root))

    status = bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert "REJECTED" in status
    assert (
        MT_FLIGHT_ACTIVITY not in bus.published
        or not bus.published[MT_FLIGHT_ACTIVITY]
    )
    assert local_name(parse_xml(bus.published[MT_MA_TASK][-1])) == "MA_Task"


def test_unavailable_rejects() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform(
        readiness=ControlReadiness(
            available=False,
            availability="TEMPORARILY_UNAVAILABLE",
        )
    )
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(tick_republish_status=False),
    )
    attach_isolator(iso)
    xml = build_sample_waypoint_command(
        iso.identity,
        command_id=uuid4(),
        capability_id=iso.ctx.state.capability_id,
    )
    bus.publish(MT_FLIGHT_COMMAND, xml)
    assert "REJECTED" in bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert MT_MA_TASK in bus.published


def test_completed_command_publishes_status_and_activity() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(tick_republish_status=False),
    )
    attach_isolator(iso)
    command_id = uuid4()
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_waypoint_command(
            iso.identity,
            command_id=command_id,
            capability_id=iso.ctx.state.capability_id,
        ),
    )
    assert "ACCEPTED" in bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert platform.complete_flight_command(command_id) == command_id
    iso.publish_command_updates_once()
    status = bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert "COMPLETED" in status
    assert command_id.hex in status.replace("-", "")
    activity = bus.published[MT_FLIGHT_ACTIVITY][-1]
    assert "COMPLETED" in activity
    assert platform.active_flight_activity() is not None
    assert platform.active_flight_activity().activity_state == "COMPLETED"
    iso.publish_command_updates_once()
    assert bus.published[MT_FLIGHT_COMMAND_STATUS][-1] == status


def test_cancel_does_not_complete() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(tick_republish_status=False),
    )
    attach_isolator(iso)
    command_id = uuid4()
    cap_id = iso.ctx.state.capability_id
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_waypoint_command(
            iso.identity,
            command_id=command_id,
            capability_id=cap_id,
        ),
    )
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_waypoint_command(
            iso.identity,
            command_id=command_id,
            capability_id=cap_id,
            command_state="CANCEL",
        ),
    )
    assert "CANCELED" in bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert platform.complete_flight_command(command_id) is None
    iso.publish_command_updates_once()
    assert "COMPLETED" not in bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
