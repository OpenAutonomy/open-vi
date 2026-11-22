"""A slow PX4 command must not stall the Isolator's periodic publishing.

Reproduces the review finding end to end: before the PX4 adapter ran
command execution on a background thread, a blocking
``submit_flight_command`` (e.g. waiting on a MISSION_START ack) shared
the single Isolator thread with the tick loop, so ``SubsystemStatus``
and ``MA_FlightCapabilityStatus`` stopped publishing for as long as the
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


class _NoMissionStartAckConn:
    """Acks the mission upload fast, but MISSION_START never gets an ACK."""

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
        # wait_command_ack's poll for MAV_CMD_MISSION_START: never arrives,
        # so the exec thread stays inside its 5s timeout for the window
        # this test checks periodic publishing against.
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

    conn = _NoMissionStartAckConn()
    plat = Px4MavlinkAdapter(connection=conn, autoconnect=False)
    plat._ingest(_FakeMsg("HEARTBEAT", base_mode=128))  # pylint: disable=protected-access
    # home_hae_m = alt - relative_alt = 100.0; armed + airborne so the
    # command is accepted under the readiness gate.
    plat._ingest(  # pylint: disable=protected-access
        _FakeMsg(
            "GLOBAL_POSITION_INT",
            lat=0,
            lon=0,
            alt=130000,
            relative_alt=30000,
            vx=0,
            vy=0,
            vz=0,
            hdg=0,
        )
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

        # MISSION_START never gets a COMMAND_ACK, so the PX4 exec thread
        # is still inside wait_command_ack for the whole window below. If
        # the Isolator thread were blocked on that call (the bug this
        # fix addresses), no further tick could publish here.
        before = len(bus.published[MT_SUBSYSTEM_STATUS])
        time.sleep(0.3)
        after = len(bus.published[MT_SUBSYSTEM_STATUS])
        assert after - before >= 3
    finally:
        iso.stop()
        plat.close()
