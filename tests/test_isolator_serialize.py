"""Isolator inbound and tick share one session writer."""

from __future__ import annotations

import threading
import time
from uuid import uuid4

from open_vi.asb import InMemoryAsb
from open_vi.codec.command import build_sample_waypoint_command
from open_vi.codec.mts import MT_FLIGHT_COMMAND, MT_FLIGHT_COMMAND_STATUS
from open_vi.config import IsolatorConfig
from open_vi.isolator import Isolator
from open_vi.platform import StubPlatform


class _OverlapPlatform(StubPlatform):
    """Fail if Isolator enters two platform methods at once."""

    def __init__(self) -> None:
        super().__init__()
        self._busy = threading.Lock()
        self.overlapped = False

    def _enter(self) -> None:
        if not self._busy.acquire(blocking=False):
            self.overlapped = True
            self._busy.acquire()

    def _leave(self) -> None:
        self._busy.release()

    def snapshot(self):  # type: ignore[override]
        self._enter()
        try:
            time.sleep(0.05)
            return super().snapshot()
        finally:
            self._leave()

    def submit_flight_command(self, cmd):  # type: ignore[override]
        self._enter()
        try:
            time.sleep(0.05)
            return super().submit_flight_command(cmd)
        finally:
            self._leave()


class _ThreadSpyPlatform(StubPlatform):
    """Record which thread submitted the flight command."""

    def __init__(self) -> None:
        super().__init__()
        self.submit_thread: str | None = None

    def submit_flight_command(self, cmd):  # type: ignore[override]
        self.submit_thread = threading.current_thread().name
        return super().submit_flight_command(cmd)


def _iso(bus: InMemoryAsb, platform: StubPlatform | None = None) -> Isolator:
    return Isolator(
        bus,
        platform=platform or StubPlatform(),
        config=IsolatorConfig(
            tick_period_s=0.2,
            tick_republish_status=False,
            publish_vehicle_state=False,
            publish_status_package=False,
        ),
    )


def test_dispatch_and_tick_do_not_interleave_platform() -> None:
    bus = InMemoryAsb()
    platform = _OverlapPlatform()
    iso = _iso(bus, platform)
    iso.attach()
    xml = build_sample_waypoint_command(
        iso.identity,
        command_id=uuid4(),
        capability_id=iso.ctx.state.capability_id,
    ).decode("utf-8")

    tick = threading.Thread(
        target=iso._tick,
        name="test-tick",  # pylint: disable=protected-access
    )
    inbound = threading.Thread(
        target=iso.dispatch, args=(MT_FLIGHT_COMMAND, xml), name="test-in"
    )
    tick.start()
    inbound.start()
    tick.join(timeout=2.0)
    inbound.join(timeout=2.0)
    assert not tick.is_alive()
    assert not inbound.is_alive()
    assert not platform.overlapped


def test_start_handles_inbound_on_isolator_thread() -> None:
    bus = InMemoryAsb()
    platform = _ThreadSpyPlatform()
    iso = _iso(bus, platform)
    iso.start()
    try:
        bus.publish(
            MT_FLIGHT_COMMAND,
            build_sample_waypoint_command(
                iso.identity,
                command_id=uuid4(),
                capability_id=iso.ctx.state.capability_id,
            ),
        )
        status = bus.wait_for(MT_FLIGHT_COMMAND_STATUS, timeout=2.0)
        assert status is not None
        assert "ACCEPTED" in status
        assert platform.submit_thread == "open-vi-isolator"
    finally:
        iso.stop()


def test_dispatch_before_start_stays_on_caller_thread() -> None:
    bus = InMemoryAsb()
    platform = _ThreadSpyPlatform()
    iso = _iso(bus, platform)
    iso.attach()
    iso.dispatch(
        MT_FLIGHT_COMMAND,
        build_sample_waypoint_command(
            iso.identity,
            command_id=uuid4(),
            capability_id=iso.ctx.state.capability_id,
        ).decode("utf-8"),
    )
    assert platform.submit_thread == threading.current_thread().name
