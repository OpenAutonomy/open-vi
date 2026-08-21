"""Isolator: Loose route upload → prepare → activate → deactivate."""

from __future__ import annotations

from uuid import uuid4

from isolator_helpers import attach_isolator
from open_vi.asb import InMemoryAsb
from open_vi.codec.command import build_sample_waypoint_command
from open_vi.codec.route import (
    build_sample_by_mission_plan_activation_command,
    build_sample_route_activation_command,
    build_sample_route_plan,
    build_sample_route_validation_command,
    parse_route_activation_commands,
    parse_route_plan_id,
)
from open_vi.codec.xmlutil import local_name, parse_xml
from open_vi.config import IsolatorConfig
from open_vi.isolator import Isolator
from open_vi.isolator.handlers.flight_command import (
    MT_FLIGHT_ACTIVITY,
    MT_FLIGHT_COMMAND,
    MT_FLIGHT_COMMAND_STATUS,
)
from open_vi.isolator.handlers.route import (
    MT_ACTIVATION_COMMAND,
    MT_ACTIVATION_STATUS,
    MT_FILE_LOCATION,
    MT_FILE_METADATA,
    MT_ROUTE_PLAN,
    MT_ROUTE_VALIDATION,
    MT_ROUTE_VALIDATION_COMMAND,
    MT_ROUTE_VALIDATION_STATUS,
    MT_SYSTEM_NOTIFICATION,
)
from open_vi.isolator.publishers import (
    MT_MISSION_PLAN_EXECUTION_STATUS,
    MT_RESPONSE_PLAN_EXECUTION_STATUS,
    MT_ROUTE_PLAN_EXECUTION_STATUS,
)
from open_vi.platform import StubPlatform


def _plan_xml(iso: Isolator, route_id, waypoints=None) -> str:
    xml = build_sample_route_plan(
        iso.identity, route_plan_id=route_id, waypoints=waypoints
    )
    return xml.decode("utf-8") if isinstance(xml, bytes) else xml


def test_parse_route_activation_command() -> None:
    bus = InMemoryAsb()
    iso = Isolator(bus, platform=StubPlatform())
    command_id = uuid4()
    mission_id = uuid4()
    route_id = uuid4()
    xml = build_sample_route_activation_command(
        iso.identity,
        command_id=command_id,
        mission_plan_id=mission_id,
        route_plan_id=route_id,
        command_type="PREPARE_FOR_UPLOAD",
    )
    cmds = parse_route_activation_commands(xml)
    assert len(cmds) == 1
    assert cmds[0].command_id == command_id
    assert cmds[0].mission_plan_id == mission_id
    assert cmds[0].route_plan_id == route_id
    assert cmds[0].command_type == "PREPARE_FOR_UPLOAD"


def test_parse_by_mission_plan_activation_command() -> None:
    bus = InMemoryAsb()
    iso = Isolator(bus, platform=StubPlatform())
    command_id = uuid4()
    mission_id = uuid4()
    xml = build_sample_by_mission_plan_activation_command(
        iso.identity,
        command_id=command_id,
        mission_plan_id=mission_id,
        command_type="PREPARE_FOR_UPLOAD",
    )
    cmds = parse_route_activation_commands(xml)
    assert len(cmds) == 1
    assert cmds[0].command_id == command_id
    assert cmds[0].mission_plan_id == mission_id
    assert cmds[0].route_plan_id == mission_id
    assert cmds[0].command_type == "PREPARE_FOR_UPLOAD"


def test_by_mission_plan_activation() -> None:
    bus = InMemoryAsb()
    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(tick_republish_status=False),
    )
    attach_isolator(iso)
    bus.publish(
        MT_ACTIVATION_COMMAND,
        build_sample_by_mission_plan_activation_command(
            iso.identity,
            command_id=uuid4(),
            mission_plan_id=uuid4(),
            command_type="PREPARE_FOR_UPLOAD",
        ),
    )
    assert len(bus.published[MT_ACTIVATION_STATUS]) == 3
    assert "QUEUED" in bus.published[MT_ACTIVATION_STATUS][0]
    assert "PROCESSING" in bus.published[MT_ACTIVATION_STATUS][1]
    assert "COMPLETED" in bus.published[MT_ACTIVATION_STATUS][2]


def test_convert_and_upload_route() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(tick_republish_status=False),
    )
    attach_isolator(iso)

    mission_id = uuid4()
    route_id = uuid4()

    prep_id = uuid4()
    bus.publish(
        MT_ACTIVATION_COMMAND,
        build_sample_route_activation_command(
            iso.identity,
            command_id=prep_id,
            mission_plan_id=mission_id,
            route_plan_id=route_id,
            command_type="PREPARE_FOR_UPLOAD",
        ),
    )
    assert len(bus.published[MT_ACTIVATION_STATUS]) == 3
    assert "PROCESSING" in bus.published[MT_ACTIVATION_STATUS][1]
    assert "COMPLETED" in bus.published[MT_ACTIVATION_STATUS][2]
    assert "READY_FOR_UPLOAD" in bus.published[MT_ACTIVATION_STATUS][2]

    plan_xml = build_sample_route_plan(iso.identity, route_plan_id=route_id)
    assert parse_route_plan_id(plan_xml) == route_id
    bus.publish(MT_ROUTE_PLAN, plan_xml)

    assert len(bus.published[MT_SYSTEM_NOTIFICATION]) == 1
    note = bus.published[MT_SYSTEM_NOTIFICATION][-1]
    assert local_name(parse_xml(note)) == "MA_SystemNotification"
    assert "CONFIRMED" in note
    assert route_id.hex in note.replace("-", "")

    assert len(bus.published[MT_FILE_LOCATION]) == 1
    assert "TEMPORARY" in bus.published[MT_FILE_LOCATION][-1]
    assert len(bus.published[MT_FILE_METADATA]) == 1
    meta = bus.published[MT_FILE_METADATA][-1]
    assert "SHA_2_Hash" in meta
    assert iso.ctx.routes.get(route_id) is not None

    upload_id = uuid4()
    before = len(bus.published[MT_ACTIVATION_STATUS])
    bus.publish(
        MT_ACTIVATION_COMMAND,
        build_sample_route_activation_command(
            iso.identity,
            command_id=upload_id,
            mission_plan_id=mission_id,
            route_plan_id=route_id,
            command_type="UPLOAD",
        ),
    )
    statuses = list(bus.published[MT_ACTIVATION_STATUS])[before:]
    assert len(statuses) == 3
    assert "UPLOADED" in statuses[2]
    assert "COMPLETED" in statuses[2]


def test_prepare_for_route_activation() -> None:
    bus = InMemoryAsb()
    route_id = uuid4()
    mission_id = uuid4()
    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(tick_republish_status=False),
    )
    iso.ctx.routes.prime(
        route_id, mission_plan_id=mission_id, state="UPLOADED", xml="<rp/>"
    )
    attach_isolator(iso)

    bus.publish(
        MT_ACTIVATION_COMMAND,
        build_sample_route_activation_command(
            iso.identity,
            command_id=uuid4(),
            mission_plan_id=mission_id,
            route_plan_id=route_id,
            command_type="PREPARE_FOR_ACTIVATION",
        ),
    )
    assert len(bus.published[MT_ACTIVATION_STATUS]) == 3
    assert "READY_FOR_ACTIVATION" in bus.published[MT_ACTIVATION_STATUS][2]
    assert "COMPLETED" in bus.published[MT_ACTIVATION_STATUS][2]


def test_activate_route() -> None:
    bus = InMemoryAsb()
    route_id = uuid4()
    mission_id = uuid4()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(tick_republish_status=False),
    )
    iso.ctx.routes.prime(
        route_id,
        mission_plan_id=mission_id,
        state="READY_FOR_ACTIVATION",
        xml=_plan_xml(iso, route_id),
    )
    attach_isolator(iso)

    bus.publish(
        MT_ACTIVATION_COMMAND,
        build_sample_route_activation_command(
            iso.identity,
            command_id=uuid4(),
            mission_plan_id=mission_id,
            route_plan_id=route_id,
            command_type="ACTIVATE",
        ),
    )
    assert len(bus.published[MT_ACTIVATION_STATUS]) == 3
    assert "ACTIVATED" in bus.published[MT_ACTIVATION_STATUS][2]
    assert "COMPLETED" in bus.published[MT_ACTIVATION_STATUS][2]
    activity = platform.active_flight_activity()
    assert activity is not None
    assert iso.ctx.flight.activity_id == activity.activity_id
    assert iso.ctx.execution.plan_id == route_id
    assert iso.ctx.execution.command_id is not None
    assert len(bus.published[MT_FLIGHT_ACTIVITY]) == 1
    assert "NEW" in bus.published[MT_FLIGHT_ACTIVITY][0]
    assert iso.ctx.execution.state == "EXECUTING"
    response = bus.published[MT_RESPONSE_PLAN_EXECUTION_STATUS][-1]
    assert "EXECUTING" in response
    assert route_id.hex in response.replace("-", "")
    assert "EXECUTING" in bus.published[MT_ROUTE_PLAN_EXECUTION_STATUS][-1]
    assert "EXECUTING" in bus.published[MT_MISSION_PLAN_EXECUTION_STATUS][-1]


def test_receive_deactivate_route() -> None:
    bus = InMemoryAsb()
    route_id = uuid4()
    mission_id = uuid4()
    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(tick_republish_status=False),
    )
    iso.ctx.routes.prime(
        route_id, mission_plan_id=mission_id, state="ACTIVATED", xml="<rp/>"
    )
    attach_isolator(iso)

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
    status = bus.published[MT_ACTIVATION_STATUS][0]
    assert "COMPLETED" in status
    assert "DEACTIVATED" in status
    assert "ACCEPTED" in status


def test_invalid_route_transition_rejected() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(tick_republish_status=False),
    )
    attach_isolator(iso)

    bus.publish(
        MT_ACTIVATION_COMMAND,
        build_sample_route_activation_command(
            iso.identity,
            command_id=uuid4(),
            mission_plan_id=uuid4(),
            route_plan_id=uuid4(),
            command_type="ACTIVATE",
        ),
    )
    assert len(bus.published[MT_ACTIVATION_STATUS]) == 1
    assert "REJECTED" in bus.published[MT_ACTIVATION_STATUS][0]
    assert "FAILED" in bus.published[MT_ACTIVATION_STATUS][0]


def test_validate_stored_route_plan() -> None:
    bus = InMemoryAsb()
    route_id = uuid4()
    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(tick_republish_status=False),
    )
    iso.ctx.routes.prime(route_id, xml=_plan_xml(iso, route_id))
    attach_isolator(iso)
    command_id = uuid4()
    bus.publish(
        MT_ROUTE_VALIDATION_COMMAND,
        build_sample_route_validation_command(
            iso.identity,
            command_id=command_id,
            route_plan_id=route_id,
        ),
    )
    validation = bus.published[MT_ROUTE_VALIDATION][-1]
    assert local_name(parse_xml(validation)) == "RoutePlanValidation"
    assert "VALID" in validation
    statuses = list(bus.published[MT_ROUTE_VALIDATION_STATUS])
    assert len(statuses) == 3
    assert "QUEUED" in statuses[0]
    assert "PROCESSING" in statuses[1]
    assert "COMPLETED" in statuses[2]
    assert command_id.hex in statuses[1].replace("-", "")


def test_validate_unknown_route_plan_invalid() -> None:
    bus = InMemoryAsb()
    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(tick_republish_status=False),
    )
    attach_isolator(iso)
    bus.publish(
        MT_ROUTE_VALIDATION_COMMAND,
        build_sample_route_validation_command(
            iso.identity,
            command_id=uuid4(),
            route_plan_id=uuid4(),
        ),
    )
    assert "INVALID" in bus.published[MT_ROUTE_VALIDATION][-1]
    assert "COMPLETED" in bus.published[MT_ROUTE_VALIDATION_STATUS][-1]


def test_validate_opaque_route_plan_invalid() -> None:
    bus = InMemoryAsb()
    route_id = uuid4()
    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(tick_republish_status=False),
    )
    iso.ctx.routes.prime(route_id, xml="<rp/>")
    attach_isolator(iso)
    bus.publish(
        MT_ROUTE_VALIDATION_COMMAND,
        build_sample_route_validation_command(
            iso.identity,
            command_id=uuid4(),
            route_plan_id=route_id,
        ),
    )
    assert "INVALID" in bus.published[MT_ROUTE_VALIDATION][-1]


def test_activate_without_waypoints_rejected() -> None:
    bus = InMemoryAsb()
    route_id = uuid4()
    mission_id = uuid4()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(tick_republish_status=False),
    )
    iso.ctx.routes.prime(
        route_id,
        mission_plan_id=mission_id,
        state="READY_FOR_ACTIVATION",
        xml="<rp/>",
    )
    attach_isolator(iso)
    bus.publish(
        MT_ACTIVATION_COMMAND,
        build_sample_route_activation_command(
            iso.identity,
            command_id=uuid4(),
            mission_plan_id=mission_id,
            route_plan_id=route_id,
            command_type="ACTIVATE",
        ),
    )
    assert len(bus.published[MT_ACTIVATION_STATUS]) == 1
    assert "REJECTED" in bus.published[MT_ACTIVATION_STATUS][0]
    stored = iso.ctx.routes.get(route_id)
    assert stored is not None
    assert stored.plan_state == "READY_FOR_ACTIVATION"
    assert platform.active_flight_activity() is None


def test_deactivate_after_activate_clears_activity() -> None:
    bus = InMemoryAsb()
    route_id = uuid4()
    mission_id = uuid4()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(tick_republish_status=False),
    )
    iso.ctx.routes.prime(
        route_id,
        mission_plan_id=mission_id,
        state="READY_FOR_ACTIVATION",
        xml=_plan_xml(iso, route_id),
    )
    attach_isolator(iso)
    bus.publish(
        MT_ACTIVATION_COMMAND,
        build_sample_route_activation_command(
            iso.identity,
            command_id=uuid4(),
            mission_plan_id=mission_id,
            route_plan_id=route_id,
            command_type="ACTIVATE",
        ),
    )
    assert platform.active_flight_activity() is not None
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
    assert platform.active_flight_activity() is None
    stored = iso.ctx.routes.get(route_id)
    assert stored is not None
    assert stored.plan_state == "DEACTIVATED"
    assert iso.ctx.execution.command_id is None
    assert iso.ctx.execution.plan_id is None
    assert iso.ctx.execution.state is None
    failed = bus.published[MT_ROUTE_PLAN_EXECUTION_STATUS][-1]
    assert "FAILED" in failed
    assert route_id.hex in failed.replace("-", "")


def test_activate_while_live_is_activity_update() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(tick_republish_status=False),
    )
    attach_isolator(iso)
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_waypoint_command(
            iso.identity,
            command_id=uuid4(),
            capability_id=iso.ctx.state.capability_id,
        ),
    )
    live = platform.active_flight_activity()
    assert live is not None
    live_id = live.activity_id
    route_id = uuid4()
    mission_id = uuid4()
    iso.ctx.routes.prime(
        route_id,
        mission_plan_id=mission_id,
        state="READY_FOR_ACTIVATION",
        xml=_plan_xml(iso, route_id),
    )
    before = len(bus.published[MT_FLIGHT_ACTIVITY])
    bus.publish(
        MT_ACTIVATION_COMMAND,
        build_sample_route_activation_command(
            iso.identity,
            command_id=uuid4(),
            mission_plan_id=mission_id,
            route_plan_id=route_id,
            command_type="ACTIVATE",
        ),
    )
    assert "ACTIVATED" in bus.published[MT_ACTIVATION_STATUS][-1]
    activity = platform.active_flight_activity()
    assert activity is not None
    assert activity.activity_id == live_id
    assert "UPDATED" in bus.published[MT_FLIGHT_ACTIVITY][before]


def test_route_sourced_complete_skips_flight_command_status() -> None:
    bus = InMemoryAsb()
    route_id = uuid4()
    mission_id = uuid4()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(tick_republish_status=False),
    )
    iso.ctx.routes.prime(
        route_id,
        mission_plan_id=mission_id,
        state="READY_FOR_ACTIVATION",
        xml=_plan_xml(iso, route_id),
    )
    attach_isolator(iso)
    bus.publish(
        MT_ACTIVATION_COMMAND,
        build_sample_route_activation_command(
            iso.identity,
            command_id=uuid4(),
            mission_plan_id=mission_id,
            route_plan_id=route_id,
            command_type="ACTIVATE",
        ),
    )
    command_id = iso.ctx.execution.command_id
    assert command_id is not None
    assert platform.complete_flight_command(command_id) == command_id
    iso.publish_command_updates_once()
    assert MT_FLIGHT_COMMAND_STATUS not in bus.published
    stored = iso.ctx.routes.get(route_id)
    assert stored is not None
    assert stored.plan_state == "ACTIVATED"
    assert iso.ctx.flight.activity_id is None
    assert iso.ctx.execution.state == "COMPLETED"
    assert "COMPLETED" in bus.published[MT_ROUTE_PLAN_EXECUTION_STATUS][-1]
    assert "COMPLETED" in bus.published[MT_RESPONSE_PLAN_EXECUTION_STATUS][-1]


def test_status_package_republishes_executing() -> None:
    bus = InMemoryAsb()
    route_id = uuid4()
    mission_id = uuid4()
    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(
            tick_republish_status=False,
            publish_status_package=True,
        ),
    )
    iso.ctx.routes.prime(
        route_id,
        mission_plan_id=mission_id,
        state="READY_FOR_ACTIVATION",
        xml=_plan_xml(iso, route_id),
    )
    attach_isolator(iso)
    bus.publish(
        MT_ACTIVATION_COMMAND,
        build_sample_route_activation_command(
            iso.identity,
            command_id=uuid4(),
            mission_plan_id=mission_id,
            route_plan_id=route_id,
            command_type="ACTIVATE",
        ),
    )
    before = len(bus.published[MT_ROUTE_PLAN_EXECUTION_STATUS])
    iso.publish_status_package_once()
    assert len(bus.published[MT_ROUTE_PLAN_EXECUTION_STATUS]) == before + 1
    assert "EXECUTING" in bus.published[MT_ROUTE_PLAN_EXECUTION_STATUS][-1]


def test_flight_command_only_skips_route_execution() -> None:
    bus = InMemoryAsb()
    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(tick_republish_status=False),
    )
    attach_isolator(iso)
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_waypoint_command(
            iso.identity,
            command_id=uuid4(),
            capability_id=iso.ctx.state.capability_id,
        ),
    )
    assert MT_ROUTE_PLAN_EXECUTION_STATUS not in bus.published
    assert MT_MISSION_PLAN_EXECUTION_STATUS not in bus.published
    iso.publish_status_package_once()
    assert MT_ROUTE_PLAN_EXECUTION_STATUS not in bus.published
    assert "ACTUAL" in bus.published[MT_RESPONSE_PLAN_EXECUTION_STATUS][-1]
