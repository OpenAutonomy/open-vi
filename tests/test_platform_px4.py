"""Px4MavlinkAdapter unit tests (mocked MAVLink; no SITL)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from open_vi.platform import (
    ControlReadiness,
    FlightCommandRequest,
    Waypoint,
    make_platform,
)
from open_vi.platform.px4 import Px4MavlinkAdapter


class _FakeMsg:
    def __init__(self, mtype: str, **fields: object) -> None:
        self._mtype = mtype
        self.__dict__.update(fields)

    def get_type(self) -> str:
        return self._mtype


class _FakeConn:
    def __init__(self) -> None:
        self.target_system = 1
        self.target_component = 1
        self.mav = SimpleNamespace(
            mission_count_send=lambda *a, **k: None,
            mission_item_int_send=lambda *a, **k: None,
            command_long_send=lambda *a, **k: None,
        )
        self._queue: list[object] = []
        self.closed = False

    def push(self, msg: object) -> None:
        self._queue.append(msg)

    def wait_heartbeat(self, timeout: float = 10.0) -> object:
        del timeout
        return _FakeMsg("HEARTBEAT", system_status=4, base_mode=0)

    def recv_match(self, **kwargs: object) -> object | None:
        del kwargs
        if self._queue:
            return self._queue.pop(0)
        return None

    def mode_mapping(self) -> dict[str, tuple[int, int, int]]:
        return {
            "TAKEOFF": (29, 4, 2),
            "MISSION": (29, 4, 4),
        }

    def set_mode(self, *args: object) -> None:
        del args

    def close(self) -> None:
        self.closed = True


def test_make_platform_stub() -> None:
    plat = make_platform("stub")
    assert plat.snapshot().readiness.available


def test_make_platform_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown platform"):
        make_platform("xplane")


def test_px4_telemetry_and_snapshot() -> None:
    conn = _FakeConn()
    plat = Px4MavlinkAdapter(connection=conn, autoconnect=False)
    conn.push(
        _FakeMsg(
            "HEARTBEAT",
            system_status=4,
            base_mode=128,
        )
    )
    plat._ingest(conn._queue.pop(0))  # pylint: disable=protected-access
    conn.push(
        _FakeMsg(
            "GLOBAL_POSITION_INT",
            lat=388895000,
            lon=-770353000,
            alt=120000,
            relative_alt=0,
            vx=100,
            vy=-50,
            vz=0,
            hdg=9000,
        )
    )
    plat._ingest(conn._queue.pop(0))  # pylint: disable=protected-access
    snap = plat.snapshot()
    assert snap.readiness.available
    assert snap.offer.capability_types == ("WAYPOINT_FOLLOWING",)
    state = plat.get_vehicle_state()
    assert state.latitude_deg == pytest.approx(38.8895)
    assert state.longitude_deg == pytest.approx(-77.0353)
    assert state.altitude_m == pytest.approx(120.0)
    assert state.north_speed_mps == pytest.approx(1.0)
    plat.close()


def test_px4_rejects_when_link_down() -> None:
    plat = Px4MavlinkAdapter(connection=None, autoconnect=False)
    result = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="WAYPOINT_FOLLOWING",
            waypoints=(Waypoint(1.0, 2.0, 50.0),),
        )
    )
    assert result.processing_state == "REJECTED"
    assert plat.snapshot().readiness == ControlReadiness(
        available=False,
        availability="TEMPORARILY_UNAVAILABLE",
        reason="PX4_LINK_DOWN",
    )


def test_px4_rejects_hsa_csa() -> None:
    conn = _FakeConn()
    plat = Px4MavlinkAdapter(connection=conn, autoconnect=False)
    plat._ingest(  # pylint: disable=protected-access
        _FakeMsg("HEARTBEAT", base_mode=0)
    )
    result = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="HSA_CSA",
            waypoints=(),
        )
    )
    assert result.processing_state == "REJECTED"
    plat.close()


def test_px4_waypoint_execute_accepts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()
    plat = Px4MavlinkAdapter(connection=conn, autoconnect=False)
    plat._ingest(  # pylint: disable=protected-access
        _FakeMsg("HEARTBEAT", base_mode=128)
    )
    # Already airborne so takeoff wait is skipped.
    plat._ingest(  # pylint: disable=protected-access
        _FakeMsg(
            "GLOBAL_POSITION_INT",
            lat=0,
            lon=0,
            alt=500000,
            relative_alt=30000,
            vx=0,
            vy=0,
            vz=0,
            hdg=0,
        )
    )

    def fake_recv_match(**kwargs: object) -> object | None:
        types = kwargs.get("type")
        if types == "MISSION_ACK":
            return _FakeMsg("MISSION_ACK", type=0)
        if types == "COMMAND_ACK":
            return _FakeMsg("COMMAND_ACK", command=400, result=0)
        if isinstance(types, list) and "MISSION_REQUEST" in types:
            return _FakeMsg("MISSION_REQUEST", seq=0)
        if types == "HEARTBEAT":
            return _FakeMsg("HEARTBEAT", base_mode=128, system_status=4)
        return None

    conn.recv_match = fake_recv_match  # type: ignore[method-assign]
    pytest.importorskip("pymavlink")

    # MISSION_START ack uses command 300.
    acks = {"arm": 400, "mission_start": 300}

    def fake_wait(command: int, timeout: float = 5.0) -> None:
        del timeout
        if command not in acks.values():
            raise TimeoutError(command)

    monkeypatch.setattr(plat, "_wait_command_ack_locked", fake_wait)

    result = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="WAYPOINT_FOLLOWING",
            waypoints=(Waypoint(10.0, 20.0, 40.0),),
        )
    )
    assert result.processing_state == "ACCEPTED"
    assert plat.active_flight_activity() is not None
    plat.close()
