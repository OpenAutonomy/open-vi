"""A slow PX4 command must not stall the Isolator's periodic publishing.

Reproduces the review finding end to end: before the PX4 adapter ran
command execution on a background thread, a blocking
``submit_flight_command`` (e.g. waiting for climb) shared the single
Isolator thread with the tick loop, so ``SubsystemStatus`` and
``MA_FlightCapabilityStatus`` stopped publishing for as long as the
command blocked.
"""

from __future__ import annotations

import time
from types import SimpleNamespace
from uuid import uuid4

import pytest

from open_vi.asb import InMemoryAsb
from open_vi.codec.command import build_sample_waypoint_command
from open_vi.codec.mts import (
    MT_FLIGHT_COMMAND,
    MT_FLIGHT_COMMAND_STATUS,
    MT_SUBSYSTEM_STATUS,
)
from open_vi.config import IsolatorConfig
from open_vi.domain import Waypoint
from open_vi.isolator import Isolator


class _FakeMsg:
    def __init__(self, mtype: str, **fields: object) -> None:
        self._mtype = mtype
        self.__dict__.update(fields)

    def get_type(self) -> str:
        return self._mtype


class _NeverAirborneConn:
    """Acks arm/mission fast, but the vehicle never reports a climb."""

    def __init__(self) -> None:
        self.target_system = 1
        self.target_component = 1
        self.mav = SimpleNamespace(
            mission_count_send=lambda *a, **k: None,
            mission_item_int_send=lambda *a, **k: None,
            command_long_send=lambda *a, **k: None,
        )

    def wait_heartbeat(self, timeout: float = 10.0) -> object:
        del timeout
        return _FakeMsg("HEARTBEAT", system_status=4, base_mode=0)

    def recv_match(self, **kwargs: object) -> object | None:
        types = kwargs.get("type")
        if types == "MISSION_ACK":
            return _FakeMsg("MISSION_ACK", type=0)
        if isinstance(types, list) and "MISSION_REQUEST" in types:
            return _FakeMsg("MISSION_REQUEST", seq=0)
        if types == "HEARTBEAT":
            return _FakeMsg("HEARTBEAT", base_mode=128, system_status=4)
        # wait_airborne's plain poll (no `type=`): relative_alt never climbs.
        time.sleep(0.01)
        return None

    def mode_mapping(self) -> dict[str, tuple[int, int, int]]:
        return {
            "TAKEOFF": (29, 4, 2),
            "MISSION": (29, 4, 4),
            "HOLD": (29, 4, 3),
        }

    def set_mode(self, *args: object) -> bool:
        del args
        return True

    def close(self) -> None:
        return


def test_slow_px4_command_does_not_stall_periodic_publishing() -> None:
    pytest.importorskip("pymavlink")
    # pylint: disable-next=import-outside-toplevel
    from open_vi.platform.px4 import Px4MavlinkAdapter

    conn = _NeverAirborneConn()
    plat = Px4MavlinkAdapter(connection=conn, autoconnect=False)
    plat._ingest(_FakeMsg("HEARTBEAT", base_mode=128))  # pylint: disable=protected-access
    plat._ingest(  # pylint: disable=protected-access
        _FakeMsg(
            "GLOBAL_POSITION_INT",
            lat=0,
            lon=0,
            alt=100000,
            relative_alt=0,
            vx=0,
            vy=0,
            vz=0,
            hdg=0,
        )
    )
    plat._wait_command_ack_locked = (  # type: ignore[method-assign]
        lambda *a, **k: None
    )

    bus = InMemoryAsb()
    iso = Isolator(
        bus,
        platform=plat,
        config=IsolatorConfig(
            tick_period_s=0.03,
            tick_republish_status=True,
            publish_vehicle_state=False,
            publish_status_package=True,
        ),
    )
    iso.start()
    try:
        xml = build_sample_waypoint_command(
            iso.identity,
            command_id=uuid4(),
            capability_id=iso.ctx.state.capability_id,
            waypoints=(
                Waypoint(
                    latitude_deg=38.0, longitude_deg=-77.0, altitude_m=130.0
                ),
            ),
        )
        bus.publish(MT_FLIGHT_COMMAND, xml)
        status = bus.wait_for(MT_FLIGHT_COMMAND_STATUS, timeout=2.0)
        assert status is not None
        assert "ACCEPTED" in status

        # The fake vehicle never reports a climb, so the PX4 exec thread
        # is still inside wait_airborne for the whole window below. If
        # the Isolator thread were blocked on that call (the bug this
        # fix addresses), no further tick could publish here.
        before = len(bus.published[MT_SUBSYSTEM_STATUS])
        time.sleep(0.3)
        after = len(bus.published[MT_SUBSYSTEM_STATUS])
        assert after - before >= 3
    finally:
        iso.stop()
        plat.close()
