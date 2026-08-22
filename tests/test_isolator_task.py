"""Isolator: inbound MA_Task, TaskCommand, and reject-suggest."""

from __future__ import annotations

from uuid import uuid4

from open_vi.asb import InMemoryAsb
from open_vi.codec.command import build_sample_waypoint_command
from open_vi.codec.mts import (
    MT_FLIGHT_COMMAND,
    MT_MA_TASK,
    MT_SYSTEM_NOTIFICATION,
    MT_TASK_COMMAND,
    MT_TASK_COMMAND_STATUS,
    MT_TASK_STATUS,
)
from open_vi.codec.task import (
    build_ma_task,
    build_sample_task_command,
    parse_ma_task,
    parse_task_commands,
)
from open_vi.codec.xmlutil import local_name, parse_xml
from open_vi.config import IsolatorConfig
from open_vi.domain import ControlReadiness
from open_vi.identity import SystemIdentity
from open_vi.isolator import Isolator
from open_vi.platform import StubPlatform


def _iso(
    bus: InMemoryAsb,
    *,
    platform: StubPlatform | None = None,
) -> Isolator:
    return Isolator(
        bus,
        platform=platform or StubPlatform(),
        config=IsolatorConfig(
            tick_republish_status=False,
            publish_vehicle_state=False,
            publish_status_package=False,
        ),
    )


def test_parse_sample_task_command() -> None:
    iso = _iso(InMemoryAsb())
    command_id = uuid4()
    task_id = uuid4()
    xml = build_sample_task_command(
        iso.identity,
        command_id=command_id,
        task_id=task_id,
        capability_id=iso.ctx.state.capability_id,
    )
    cmds = parse_task_commands(xml)
    assert len(cmds) == 1
    assert cmds[0].command_id == command_id
    assert cmds[0].task_id == task_id


def test_task_command_accepted() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    task_id = uuid4()
    command_id = uuid4()
    bus.publish(
        MT_TASK_COMMAND,
        build_sample_task_command(
            iso.identity,
            command_id=command_id,
            task_id=task_id,
            capability_id=iso.ctx.state.capability_id,
        ),
    )
    status = bus.published[MT_TASK_COMMAND_STATUS][-1]
    assert local_name(parse_xml(status)) == "MA_TaskCommandStatus"
    assert "ACCEPTED" in status
    assert command_id.hex in status.replace("-", "")
    task_status = bus.published[MT_TASK_STATUS][-1]
    assert local_name(parse_xml(task_status)) == "TaskStatus"
    assert "EXECUTING" in task_status
    assert task_id.hex in task_status.replace("-", "")
    assert iso.ctx.state.active_task_id == task_id


def test_flight_command_reject_suggests_task() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform(
        readiness=ControlReadiness(
            available=False,
            availability="TEMPORARILY_UNAVAILABLE",
        )
    )
    iso = _iso(bus, platform=platform)
    iso.attach()
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_waypoint_command(
            iso.identity,
            command_id=uuid4(),
            capability_id=iso.ctx.state.capability_id,
        ),
    )
    task = bus.published[MT_MA_TASK][-1]
    assert local_name(parse_xml(task)) == "MA_Task"
    assert "CapabilityType" in task
    assert "MUST_FLY" in task


def test_task_command_cancel_publishes_task_status() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    task_id = uuid4()
    command_id = uuid4()
    bus.publish(
        MT_TASK_COMMAND,
        build_sample_task_command(
            iso.identity,
            command_id=command_id,
            task_id=task_id,
            capability_id=iso.ctx.state.capability_id,
            command_state="CANCEL",
        ),
    )
    status = bus.published[MT_TASK_COMMAND_STATUS][-1]
    assert "CANCELED" in status
    task_status = bus.published[MT_TASK_STATUS][-1]
    assert "CANCELED" in task_status
    assert iso.ctx.state.active_task_id is None


def test_parse_ma_task() -> None:
    iso = _iso(InMemoryAsb())
    task_id = uuid4()
    parsed = parse_ma_task(build_ma_task(iso.identity, task_id=task_id))
    assert parsed is not None
    assert parsed.task_id == task_id
    assert parsed.object_state == "NEW"


def test_inbound_task_notifies() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    task_id = uuid4()
    bus.publish(
        MT_MA_TASK,
        build_ma_task(SystemIdentity.named("ma-tasker"), task_id=task_id),
    )
    assert task_id in iso.ctx.state.ingested_task_ids
    note = bus.published[MT_SYSTEM_NOTIFICATION][-1]
    assert "MA_TASK" in note
    assert task_id.hex in note.replace("-", "")


def test_inbound_task_duplicate_does_not_renotify() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    task_id = uuid4()
    xml = build_ma_task(SystemIdentity.named("ma-tasker"), task_id=task_id)
    bus.publish(MT_MA_TASK, xml)
    bus.publish(MT_MA_TASK, xml)
    assert len(bus.published[MT_SYSTEM_NOTIFICATION]) == 1


def test_own_suggest_task_is_not_ingested() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform(
        readiness=ControlReadiness(
            available=False,
            availability="TEMPORARILY_UNAVAILABLE",
        )
    )
    iso = _iso(bus, platform=platform)
    iso.attach()
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_waypoint_command(
            iso.identity,
            command_id=uuid4(),
            capability_id=iso.ctx.state.capability_id,
        ),
    )
    assert MT_SYSTEM_NOTIFICATION not in bus.published
    assert not iso.ctx.state.ingested_task_ids


def test_removed_task_clears_ingest() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    task_id = uuid4()
    peer = SystemIdentity.named("ma-tasker")
    bus.publish(MT_MA_TASK, build_ma_task(peer, task_id=task_id))
    bus.publish(
        MT_MA_TASK,
        build_ma_task(peer, task_id=task_id, object_state="REMOVED"),
    )
    assert task_id not in iso.ctx.state.ingested_task_ids
    assert len(bus.published[MT_SYSTEM_NOTIFICATION]) == 1
