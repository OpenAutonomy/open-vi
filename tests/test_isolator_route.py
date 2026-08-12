"""Isolator: Loose route upload → prepare → activate → deactivate."""

from __future__ import annotations

from uuid import uuid4

from isolator_helpers import attach_isolator
from open_vi.asb import InMemoryAsb
from open_vi.codec.route import (
    build_sample_route_activation_command,
    build_sample_route_plan,
    parse_route_activation_commands,
    parse_route_plan_id,
)
from open_vi.codec.xmlutil import local_name, parse_xml
from open_vi.config import IsolatorConfig
from open_vi.isolator import Isolator
from open_vi.isolator.handlers.route import (
    MT_ACTIVATION_COMMAND,
    MT_ACTIVATION_STATUS,
    MT_FILE_LOCATION,
    MT_FILE_METADATA,
    MT_ROUTE_PLAN,
    MT_SYSTEM_NOTIFICATION,
)
from open_vi.platform import StubPlatform


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


def test_convert_and_upload_route_loose() -> None:
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
    assert len(bus.published[MT_ACTIVATION_STATUS]) == 2
    assert "PROCESSING" in bus.published[MT_ACTIVATION_STATUS][0]
    assert "COMPLETED" in bus.published[MT_ACTIVATION_STATUS][1]
    assert "READY_FOR_UPLOAD" in bus.published[MT_ACTIVATION_STATUS][1]

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
    assert platform.get_stored_route(route_id) is not None

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
    assert len(statuses) == 2
    assert "UPLOADED" in statuses[1]
    assert "COMPLETED" in statuses[1]


def test_prepare_for_route_activation() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    route_id = uuid4()
    mission_id = uuid4()
    platform.prime_route(
        route_id, mission_plan_id=mission_id, state="UPLOADED", xml="<rp/>"
    )
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
            mission_plan_id=mission_id,
            route_plan_id=route_id,
            command_type="PREPARE_FOR_ACTIVATION",
        ),
    )
    assert len(bus.published[MT_ACTIVATION_STATUS]) == 2
    assert "READY_FOR_ACTIVATION" in bus.published[MT_ACTIVATION_STATUS][1]
    assert "COMPLETED" in bus.published[MT_ACTIVATION_STATUS][1]


def test_activate_route() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    route_id = uuid4()
    mission_id = uuid4()
    platform.prime_route(
        route_id,
        mission_plan_id=mission_id,
        state="READY_FOR_ACTIVATION",
        xml="<rp/>",
    )
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
            mission_plan_id=mission_id,
            route_plan_id=route_id,
            command_type="ACTIVATE",
        ),
    )
    assert len(bus.published[MT_ACTIVATION_STATUS]) == 2
    assert "ACTIVATED" in bus.published[MT_ACTIVATION_STATUS][1]
    assert "COMPLETED" in bus.published[MT_ACTIVATION_STATUS][1]


def test_receive_deactivate_route_loose() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    route_id = uuid4()
    mission_id = uuid4()
    platform.prime_route(
        route_id, mission_plan_id=mission_id, state="ACTIVATED", xml="<rp/>"
    )
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
