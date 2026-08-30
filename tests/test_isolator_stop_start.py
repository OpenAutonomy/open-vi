"""stop()/start() must not let two Isolator threads run at once.

Before this fix, stop()'s fixed join timeout cleared ``_thread``
unconditionally, and start() unconditionally cleared the shared
``_stop``/``_wakeup`` events before spawning a new thread. If the
old thread was still stuck past the join timeout, a later start()
would clear the events out from under it and spawn a second thread:
once the old thread's blocking call finally returned, it would see
``_stop`` cleared and keep looping alongside the new thread.
"""

from __future__ import annotations

import threading

import pytest

from open_vi.asb import InMemoryAsb
from open_vi.config import IsolatorConfig
from open_vi.isolator import Isolator
from open_vi.platform import StubPlatform


class _StuckPlatform(StubPlatform):
    """Blocks ``poll_command_updates()`` until released.

    ``_tick()`` calls this before ``snapshot()``, so this blocks only
    the tick loop -- unlike ``snapshot()``, it is not also called by
    ``start()``'s own synchronous ``advertise_control()``.
    """

    def __init__(self) -> None:
        super().__init__()
        self.entered = threading.Event()
        self.release = threading.Event()

    def poll_command_updates(self):  # type: ignore[override]
        self.entered.set()
        self.release.wait()
        return super().poll_command_updates()


def _iso(
    bus: InMemoryAsb, platform: StubPlatform, *, tick_period_s: float
) -> Isolator:
    return Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(
            tick_period_s=tick_period_s,
            tick_republish_status=False,
            publish_vehicle_state=False,
            publish_status_package=False,
        ),
    )


def test_start_refuses_when_already_running() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus, StubPlatform(), tick_period_s=0.2)
    iso.start()
    try:
        with pytest.raises(RuntimeError):
            iso.start()
    finally:
        iso.stop()


def test_stop_timeout_leaves_thread_tracked_and_start_refuses() -> None:
    bus = InMemoryAsb()
    platform = _StuckPlatform()
    iso = _iso(bus, platform, tick_period_s=0.01)
    iso.start()
    assert platform.entered.wait(timeout=2.0)

    # The tick loop is stuck inside snapshot(); a short join can't
    # catch it, so stop() must not clear the thread it couldn't join.
    iso.stop(timeout=0.05)

    # A second start() must refuse rather than spawn a thread that
    # would race the one still stuck inside snapshot().
    with pytest.raises(RuntimeError):
        iso.start()

    # Unblock the stuck call so the old thread can exit on its own —
    # start() never cleared _stop, so its loop condition stays false.
    platform.release.set()
    old_thread = iso._thread  # pylint: disable=protected-access
    assert old_thread is not None
    old_thread.join(timeout=2.0)
    assert not old_thread.is_alive()

    # Now that the old thread has actually exited, start() succeeds.
    iso.start()
    iso.stop()
