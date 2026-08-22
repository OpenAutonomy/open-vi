"""Px4MavlinkAdapter unit tests (mocked MAVLink; no SITL)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from open_vi.domain import (
    ControlReadiness,
    CurveControlPoint,
    CurveFollowingSetpoint,
    FlightCommandRequest,
    HsaCsaSetpoint,
    Waypoint,
)
from open_vi.platform import make_platform
from open_vi.platform.px4 import Px4MavlinkAdapter

# Airborne fixture home HAE is 470 m; these are 30 m and 50 m AGL.
_IN_BAND = Waypoint(10.0, 20.0, 500.0)
_IN_BAND_2 = Waypoint(11.0, 21.0, 520.0)


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
        self.param_sets: list[tuple[tuple[object, ...], dict[str, object]]] = []
        self.position_targets: list[tuple[tuple[object, ...], dict]] = []
        self.mav = SimpleNamespace(
            mission_count_send=lambda *a, **k: None,
            mission_item_int_send=lambda *a, **k: None,
            command_long_send=lambda *a, **k: None,
            param_set_send=self._param_set,
            set_position_target_local_ned_send=self._set_ned,
        )

        self._queue: list[object] = []
        self.closed = False

    def _param_set(self, *args: object, **kwargs: object) -> None:
        self.param_sets.append((args, kwargs))

    def _set_ned(self, *args: object, **kwargs: object) -> None:
        self.position_targets.append((args, kwargs))

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
            "HOLD": (29, 4, 3),
            "OFFBOARD": (29, 4, 6),
        }

    def set_mode(self, *args: object) -> None:
        del args

    def close(self) -> None:
        self.closed = True


def test_import_platform_package_does_not_load_px4() -> None:
    import sys

    sys.modules.pop("open_vi.platform.px4", None)
    sys.modules.pop("open_vi.platform", None)
    import open_vi.platform as platform

    assert "open_vi.platform.px4" not in sys.modules
    assert hasattr(platform, "make_platform")


def test_make_platform_stub() -> None:
    plat = make_platform("stub")
    assert plat.snapshot().readiness.available


def test_make_platform_stub_does_not_import_px4() -> None:
    import sys

    sys.modules.pop("open_vi.platform.px4", None)
    make_platform("stub")
    assert "open_vi.platform.px4" not in sys.modules


def test_make_platform_px4_imports_lazily() -> None:
    import sys

    sys.modules.pop("open_vi.platform.px4", None)
    plat = make_platform("px4", autoconnect=False)
    assert "open_vi.platform.px4" in sys.modules
    plat.close()


def test_make_platform_unknown() -> None:
    with pytest.raises(ValueError, match="Unknown platform"):
        make_platform("xplane")


def test_px4_path_clearance_constructor_overrides_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PX4_PATH_CLEARANCE_M", "12.5")
    plat = Px4MavlinkAdapter(
        connection=_FakeConn(),
        autoconnect=False,
        path_clearance_m=25.0,
    )
    assert plat._path_clearance_m == 25.0  # pylint: disable=protected-access
    plat.close()


def test_px4_path_clearance_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PX4_PATH_CLEARANCE_M", "12.5")
    plat = Px4MavlinkAdapter(connection=_FakeConn(), autoconnect=False)
    assert plat._path_clearance_m == 12.5  # pylint: disable=protected-access
    plat.close()


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
    assert snap.offer.capability_types == (
        "WAYPOINT_FOLLOWING",
        "HSA_CSA",
        "CURVE_FOLLOWING",
    )
    assert snap.offer.curve_profile is not None
    assert snap.offer.hsa_profile is not None
    profile = snap.offer.waypoint_profile
    assert profile is not None
    assert profile.altitude_ref == "WGS_HAE"
    assert profile.min_altitude_m == pytest.approx(130.0)
    assert profile.max_altitude_m == pytest.approx(620.0)
    hsa_profile = snap.offer.hsa_profile
    assert hsa_profile.min_altitude_m == pytest.approx(120.0)
    assert hsa_profile.max_altitude_m == pytest.approx(620.0)
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


def _sample_curve(
    *, center_alt_m: float | None = None
) -> CurveFollowingSetpoint:
    return CurveFollowingSetpoint(
        center_lat_deg=38.8895,
        center_lon_deg=-77.0353,
        center_alt_m=center_alt_m,
        control_points=(
            CurveControlPoint(0.0, 0.0),
            CurveControlPoint(100.0, 0.0),
            CurveControlPoint(200.0, 0.0),
            CurveControlPoint(300.0, 0.0),
        ),
        knots=(0.0, 0.0, 1.0, 1.0),
    )


def test_px4_rejects_empty_curve() -> None:
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
            mode="CURVE_FOLLOWING",
            waypoints=(),
        )
    )
    assert result.processing_state == "REJECTED"
    assert result.validation_results == ("INVALID_WAYPOINT",)
    plat.close()


def test_px4_curve_execute_accepts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plat = _airborne_px4(monkeypatch)
    result = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="CURVE_FOLLOWING",
            curve=_sample_curve(center_alt_m=500.0),
        )
    )
    assert result.processing_state == "ACCEPTED"
    assert result.activity_id is not None
    plat.close()


def test_px4_curve_rejects_out_of_envelope() -> None:
    conn = _FakeConn()
    plat = Px4MavlinkAdapter(connection=conn, autoconnect=False)
    plat._ingest(  # pylint: disable=protected-access
        _FakeMsg("HEARTBEAT", base_mode=128)
    )
    plat._ingest(  # pylint: disable=protected-access
        _FakeMsg(
            "GLOBAL_POSITION_INT",
            lat=0,
            lon=0,
            alt=470000,
            relative_alt=0,
            vx=0,
            vy=0,
            vz=0,
            hdg=0,
        )
    )
    result = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="CURVE_FOLLOWING",
            curve=_sample_curve(center_alt_m=471.0),
        )
    )
    assert result.processing_state == "REJECTED"
    assert result.validation_results == ("PERFORMANCE_LIMIT_EXCEEDED",)
    plat.close()


def test_px4_rejects_hsa_magnetic() -> None:
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
            hsa=HsaCsaSetpoint(
                heading_deg=90.0,
                heading_ref="MAGNETIC_NORTH",
            ),
        )
    )
    assert result.processing_state == "REJECTED"
    assert result.validation_results == ("CAPABILITY_NOT_SUPPORTED",)
    plat.close()


def test_px4_rejects_hsa_tas() -> None:
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
            hsa=HsaCsaSetpoint(
                speed_mps=10.0,
                speed_ref="TRUE_AIRSPEED",
            ),
        )
    )
    assert result.processing_state == "REJECTED"
    assert result.validation_results == ("CAPABILITY_NOT_SUPPORTED",)
    plat.close()


def test_mission_rel_alt_subtracts_home_hae() -> None:
    plat = Px4MavlinkAdapter(connection=_FakeConn(), autoconnect=False)
    plat._ingest(  # pylint: disable=protected-access
        _FakeMsg(
            "GLOBAL_POSITION_INT",
            lat=473980000,
            lon=85460000,
            alt=420_000,
            relative_alt=0,
            vx=0,
            vy=0,
            vz=0,
            hdg=0,
        )
    )
    rel = plat._mission_rel_alt_m(470.0)  # pylint: disable=protected-access
    assert rel == 50.0
    floor = plat._mission_rel_alt_m(10.0)  # pylint: disable=protected-access
    assert floor == 30.0


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
            waypoints=(_IN_BAND,),
        )
    )
    assert result.processing_state == "ACCEPTED"
    assert plat.active_flight_activity() is not None
    plat.close()


def test_px4_mission_reached_completes_last_waypoint() -> None:
    conn = _FakeConn()
    plat = Px4MavlinkAdapter(connection=conn, autoconnect=False)
    plat._ingest(  # pylint: disable=protected-access
        _FakeMsg("HEARTBEAT", base_mode=128)
    )
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
    command_id = uuid4()

    def fake_recv_match(**kwargs: object) -> object | None:
        types = kwargs.get("type")
        if types == "MISSION_ACK":
            return _FakeMsg("MISSION_ACK", type=0)
        if isinstance(types, list) and "MISSION_REQUEST" in types:
            return _FakeMsg("MISSION_REQUEST", seq=0)
        return None

    conn.recv_match = fake_recv_match  # type: ignore[method-assign]
    pytest.importorskip("pymavlink")

    def fake_wait(command: int, timeout: float = 5.0) -> None:
        del command, timeout

    plat._wait_command_ack_locked = fake_wait  # type: ignore[method-assign]
    result = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=command_id,
            capability_id=uuid4(),
            command_state="NEW",
            mode="WAYPOINT_FOLLOWING",
            waypoints=(_IN_BAND,),
        )
    )
    assert result.processing_state == "ACCEPTED"
    # Already airborne: takeoff is omitted, so the only item is seq 0.
    plat._ingest(  # pylint: disable=protected-access
        _FakeMsg("MISSION_ITEM_REACHED", seq=0)
    )
    updates = plat.poll_command_updates()
    assert len(updates) == 1
    assert updates[0][0] == command_id
    assert updates[0][1].processing_state == "COMPLETED"
    assert plat.active_flight_activity() is not None
    assert plat.active_flight_activity().activity_state == "COMPLETED"
    assert plat.poll_command_updates() == []
    plat.close()


def test_px4_cancel_ignores_later_mission_reached(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conn = _FakeConn()
    plat = Px4MavlinkAdapter(connection=conn, autoconnect=False)
    plat._ingest(  # pylint: disable=protected-access
        _FakeMsg("HEARTBEAT", base_mode=128)
    )
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
    command_id = uuid4()
    capability_id = uuid4()

    def fake_recv_match(**kwargs: object) -> object | None:
        types = kwargs.get("type")
        if types == "MISSION_ACK":
            return _FakeMsg("MISSION_ACK", type=0)
        if isinstance(types, list) and "MISSION_REQUEST" in types:
            return _FakeMsg("MISSION_REQUEST", seq=0)
        return None

    conn.recv_match = fake_recv_match  # type: ignore[method-assign]
    pytest.importorskip("pymavlink")
    monkeypatch.setattr(plat, "_wait_command_ack_locked", lambda *a, **k: None)
    plat.submit_flight_command(
        FlightCommandRequest(
            command_id=command_id,
            capability_id=capability_id,
            command_state="NEW",
            mode="WAYPOINT_FOLLOWING",
            waypoints=(_IN_BAND,),
        )
    )
    canceled = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=command_id,
            capability_id=capability_id,
            command_state="CANCEL",
            mode="WAYPOINT_FOLLOWING",
        )
    )
    assert canceled.processing_state == "CANCELED"
    plat._ingest(  # pylint: disable=protected-access
        _FakeMsg("MISSION_ITEM_REACHED", seq=1)
    )
    assert plat.poll_command_updates() == []
    plat.close()


def _airborne_px4(monkeypatch: pytest.MonkeyPatch) -> Px4MavlinkAdapter:
    conn = _FakeConn()
    plat = Px4MavlinkAdapter(connection=conn, autoconnect=False)
    plat._ingest(  # pylint: disable=protected-access
        _FakeMsg("HEARTBEAT", base_mode=128)
    )
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
    monkeypatch.setattr(plat, "_wait_command_ack_locked", lambda *a, **k: None)
    return plat


def test_px4_activity_update_keeps_activity_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plat = _airborne_px4(monkeypatch)
    first = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="WAYPOINT_FOLLOWING",
            waypoints=(_IN_BAND,),
        )
    )
    assert first.processing_state == "ACCEPTED"
    live = first.activity_id
    assert live is not None
    updated = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="UPDATE",
            mode="WAYPOINT_FOLLOWING",
            waypoints=(_IN_BAND_2,),
            choice="Activity",
            activity_id=live,
        )
    )
    assert updated.processing_state == "ACCEPTED"
    assert updated.new_activity is False
    assert updated.activity_id == live
    assert plat.active_flight_activity() is not None
    assert plat.active_flight_activity().activity_id == live
    plat.close()


def test_px4_capability_new_while_live_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plat = _airborne_px4(monkeypatch)
    first = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="WAYPOINT_FOLLOWING",
            waypoints=(_IN_BAND,),
        )
    )
    assert first.processing_state == "ACCEPTED"
    second = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="WAYPOINT_FOLLOWING",
            waypoints=(_IN_BAND_2,),
        )
    )
    assert second.processing_state == "REJECTED"
    assert plat.active_flight_activity() is not None
    assert plat.active_flight_activity().activity_id == first.activity_id
    plat.close()


def test_px4_activity_update_unknown_id_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plat = _airborne_px4(monkeypatch)
    plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="WAYPOINT_FOLLOWING",
            waypoints=(_IN_BAND,),
        )
    )
    result = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="UPDATE",
            mode="WAYPOINT_FOLLOWING",
            waypoints=(_IN_BAND_2,),
            choice="Activity",
            activity_id=uuid4(),
        )
    )
    assert result.processing_state == "REJECTED"
    assert result.reason == "INVALID_INPUT_PARAMETER"
    plat.close()


def test_advance_skips_captured_and_behind_waypoints() -> None:
    from open_vi.platform.px4 import advance_mission_waypoints

    here = (47.3980, 8.5400)
    behind = Waypoint(47.3980, 8.5420, 50.0)  # east of here, goal is west
    captured = Waypoint(47.3980, 8.5401, 50.0)
    ahead = Waypoint(47.3980, 8.5360, 50.0)
    goal = Waypoint(47.3980, 8.5300, 50.0)
    kept = advance_mission_waypoints((behind, captured, ahead, goal), here)
    assert kept == (ahead, goal)


def test_advance_keeps_goal_when_all_prefix_is_behind() -> None:
    from open_vi.platform.px4 import advance_mission_waypoints

    here = (47.3980, 8.5400)
    behind = Waypoint(47.3980, 8.5450, 50.0)
    goal = Waypoint(47.3980, 8.5300, 50.0)
    assert advance_mission_waypoints((behind, goal), here) == (goal,)


def test_px4_rejects_out_of_envelope_before_mission(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plat = _airborne_px4(monkeypatch)
    sent: list[int] = []
    plat._conn.mav.mission_count_send = (  # type: ignore[union-attr]
        lambda *a, **k: sent.append(1)
    )
    result = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="WAYPOINT_FOLLOWING",
            waypoints=(Waypoint(10.0, 20.0, 2000.0),),
        )
    )
    assert result.processing_state == "REJECTED"
    assert result.validation_results == ("PERFORMANCE_LIMIT_EXCEEDED",)
    assert sent == []
    plat.close()


def test_px4_qnh_writes_param() -> None:
    pytest.importorskip("pymavlink")
    conn = _FakeConn()
    plat = Px4MavlinkAdapter(connection=conn, autoconnect=False)
    plat._ingest(_FakeMsg("HEARTBEAT", base_mode=0))  # pylint: disable=protected-access

    def fake_recv(**kwargs: object) -> object | None:
        if kwargs.get("type") == "PARAM_VALUE":
            return _FakeMsg(
                "PARAM_VALUE",
                param_id=b"SENS_BARO_QNH",
                param_value=1013.25,
            )
        return None

    conn.recv_match = fake_recv  # type: ignore[method-assign]
    assert plat.apply_system_management(qnh_kpa=101.325) == "COMPLETED"
    assert conn.param_sets
    assert plat.get_vehicle_state().kollsman_hpa == pytest.approx(1013.25)
    plat.close()


def test_px4_qnh_link_down_rejected() -> None:
    plat = Px4MavlinkAdapter(connection=None, autoconnect=False)
    assert plat.apply_system_management(qnh_kpa=101.325) == "REJECTED"
    plat.close()


def _hsa_in_band() -> HsaCsaSetpoint:
    return HsaCsaSetpoint(
        altitude_m=50.0,
        altitude_ref="AGL",
        speed_mps=5.0,
        speed_ref="GROUNDSPEED",
        heading_deg=90.0,
        direction_kind="HEADING",
        heading_ref="TRUE_NORTH",
    )


def test_px4_hsa_accepts_and_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("pymavlink")
    plat = _airborne_px4(monkeypatch)
    conn = plat._conn
    assert conn is not None
    result = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="HSA_CSA",
            hsa=_hsa_in_band(),
        )
    )
    assert result.processing_state == "ACCEPTED"
    assert result.activity_id is not None
    assert plat.active_flight_activity() is not None
    assert conn.position_targets
    live = plat._hsa_live  # pylint: disable=protected-access
    assert live is not None
    assert live.heading_deg == pytest.approx(90.0)
    assert live.speed_mps == pytest.approx(5.0)
    assert live.rel_alt_m == pytest.approx(50.0)
    plat.close()
    assert plat._offboard_thread is None  # pylint: disable=protected-access


def test_px4_hsa_empty_holds_current(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("pymavlink")
    plat = _airborne_px4(monkeypatch)
    result = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="HSA_CSA",
            hsa=HsaCsaSetpoint(),
        )
    )
    assert result.processing_state == "ACCEPTED"
    live = plat._hsa_live  # pylint: disable=protected-access
    assert live is not None
    assert live.heading_deg == pytest.approx(0.0)
    assert live.speed_mps == pytest.approx(0.0)
    assert live.rel_alt_m == pytest.approx(30.0)
    plat.close()


def test_px4_hsa_ground_hae_climbs_to_takeoff() -> None:
    plat = Px4MavlinkAdapter(connection=_FakeConn(), autoconnect=False)
    plat._ingest(  # pylint: disable=protected-access
        _FakeMsg("HEARTBEAT", base_mode=0)
    )
    plat._ingest(  # pylint: disable=protected-access
        _FakeMsg(
            "GLOBAL_POSITION_INT",
            lat=0,
            lon=0,
            alt=489429,
            relative_alt=0,
            vx=0,
            vy=0,
            vz=0,
            hdg=0,
        )
    )
    live = plat._resolve_hsa(  # pylint: disable=protected-access
        HsaCsaSetpoint(altitude_m=489.4, altitude_ref="WGS_HAE")
    )
    assert live.rel_alt_m == pytest.approx(30.0)
    plat.close()


def test_px4_hsa_execution_fail_uses_state_or_settings(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plat = _airborne_px4(monkeypatch)

    def fail(_hsa: HsaCsaSetpoint) -> None:
        raise RuntimeError("COMMAND_ACK command=400 result=1")

    monkeypatch.setattr(plat, "_execute_hsa_csa", fail)
    result = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="HSA_CSA",
            hsa=_hsa_in_band(),
        )
    )
    assert result.processing_state == "REJECTED"
    assert result.reason == "STATE_OR_SETTINGS"
    plat.close()


def test_px4_hsa_activity_update_replaces_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("pymavlink")
    plat = _airborne_px4(monkeypatch)
    first = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="HSA_CSA",
            hsa=_hsa_in_band(),
        )
    )
    assert first.processing_state == "ACCEPTED"
    live_id = first.activity_id
    updated = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="UPDATE",
            mode="HSA_CSA",
            choice="Activity",
            activity_id=live_id,
            hsa=HsaCsaSetpoint(
                altitude_m=60.0,
                altitude_ref="AGL",
                speed_mps=8.0,
                speed_ref="GROUNDSPEED",
                heading_deg=180.0,
                heading_ref="TRUE_NORTH",
            ),
        )
    )
    assert updated.processing_state == "ACCEPTED"
    assert updated.new_activity is False
    assert updated.activity_id == live_id
    live = plat._hsa_live  # pylint: disable=protected-access
    assert live is not None
    assert live.heading_deg == pytest.approx(180.0)
    assert live.speed_mps == pytest.approx(8.0)
    assert live.rel_alt_m == pytest.approx(60.0)
    plat.close()


def test_px4_hsa_cancel_stops_stream(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("pymavlink")
    plat = _airborne_px4(monkeypatch)
    command_id = uuid4()
    first = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=command_id,
            capability_id=uuid4(),
            command_state="NEW",
            mode="HSA_CSA",
            hsa=_hsa_in_band(),
        )
    )
    assert first.processing_state == "ACCEPTED"
    canceled = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=command_id,
            capability_id=uuid4(),
            command_state="CANCEL",
            mode="HSA_CSA",
        )
    )
    assert canceled.processing_state == "CANCELED"
    assert plat.active_flight_activity() is None
    assert plat._hsa_live is None  # pylint: disable=protected-access
    assert plat._offboard_thread is None  # pylint: disable=protected-access
    plat.close()


def test_px4_hsa_capability_new_while_live_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("pymavlink")
    plat = _airborne_px4(monkeypatch)
    first = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="HSA_CSA",
            hsa=_hsa_in_band(),
        )
    )
    assert first.processing_state == "ACCEPTED"
    second = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="HSA_CSA",
            hsa=_hsa_in_band(),
        )
    )
    assert second.processing_state == "REJECTED"
    assert plat.active_flight_activity() is not None
    plat.close()


def test_px4_hsa_rejects_out_of_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plat = _airborne_px4(monkeypatch)
    conn = plat._conn
    assert conn is not None
    result = plat.submit_flight_command(
        FlightCommandRequest(
            command_id=uuid4(),
            capability_id=uuid4(),
            command_state="NEW",
            mode="HSA_CSA",
            hsa=HsaCsaSetpoint(altitude_m=501.0, altitude_ref="AGL"),
        )
    )
    assert result.processing_state == "REJECTED"
    assert result.validation_results == ("PERFORMANCE_LIMIT_EXCEEDED",)
    assert conn.position_targets == []
    plat.close()
