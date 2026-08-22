"""PX4 / SITL :class:`PlatformPort` via MAVLink (pymavlink).

Telemetry, ``WAYPOINT_FOLLOWING``, ``CURVE_FOLLOWING`` (sampled
NURBS as a mission), and ``HSA_CSA`` (offboard hold).
Isolator and the codec never import this module or MAVLink types —
``make_platform("px4")`` loads it. Arm, takeoff, and mission start
stay inside the adapter; Mission Autonomy sends
``MA_FlightCommand``, not UCI arm. Default link is
``udpin:127.0.0.1:14540``. Install pymavlink with
``pip install -e ".[px4]"``.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from dataclasses import dataclass, replace
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from open_vi.domain import (
    CommandResult,
    ControlOffer,
    ControlReadiness,
    CurveFollowingSetpoint,
    FaultSnapshot,
    FlightActivitySnapshot,
    FlightCommandRequest,
    FlightModeProfile,
    HsaCsaSetpoint,
    PlatformSnapshot,
    ServiceStatusSnapshot,
    SubsystemStatusSnapshot,
    TspiSnapshot,
    Waypoint,
    is_live_activity,
    sample_curve_waypoints,
    validate_curve_following,
    validate_hsa_setpoint,
    validate_waypoint_path,
)
from open_vi.platform.port import PlatformPort

LOGGER = logging.getLogger(__name__)


_EARTH_M = 6_378_137.0
# Adapter acceptance radius written to NAV_ACC_RAD / NAV_MC_ALT_RAD.
DEFAULT_PATH_CLEARANCE_M = 15.0
DEFAULT_MIN_REL_ALT_M = 10.0
DEFAULT_MAX_REL_ALT_M = 500.0
_QNH_PARAM = "SENS_BARO_QNH"
_ISA_T0_K = 288.15
_ISA_L_K_PER_M = 0.0065
_ISA_P0_PA = 101325.0
_ISA_G = 9.80665
_ISA_R = 287.05
_ISA_GAMMA = 1.4
_ISA_RHO0 = 1.225
_TROPO_MAX_M = 11000.0
_HDG_UNKNOWN_CDEG = 65535.0
_TEMP_MIN_K = 150.0
_TEMP_MAX_K = 400.0
_FAULT_NS = uuid5(NAMESPACE_URL, "https://openautonomy.org/open-vi/px4")
# MAV_SYS_STATUS_SENSOR_* bits PX4 reports on SYS_STATUS.
_SENSOR_BITS: tuple[tuple[int, str, str], ...] = (
    (1, "SENSOR_3D_GYRO", "3D gyro unhealthy"),
    (2, "SENSOR_3D_ACCEL", "3D accel unhealthy"),
    (4, "SENSOR_3D_MAG", "3D mag unhealthy"),
    (8, "SENSOR_BARO", "Absolute pressure unhealthy"),
    (16, "SENSOR_DIFF_PRESSURE", "Differential pressure unhealthy"),
    (32, "SENSOR_GPS", "GPS unhealthy"),
    (32768, "SENSOR_MOTOR_OUTPUTS", "Motor outputs unhealthy"),
    (65536, "SENSOR_RC_RECEIVER", "RC receiver unhealthy"),
    (2097152, "SENSOR_AHRS", "AHRS unhealthy"),
    (33554432, "SENSOR_BATTERY", "Battery unhealthy"),
)


def _isa_temperature_k(alt_m: float) -> float:
    """ISA troposphere temperature (K) from AMSL metres."""
    height = min(max(alt_m, 0.0), _TROPO_MAX_M)
    return _ISA_T0_K - _ISA_L_K_PER_M * height


def _isa_pressure_pa(alt_m: float) -> float:
    """ISA troposphere static pressure (Pa) from AMSL metres."""
    temp_k = _isa_temperature_k(alt_m)
    exponent = _ISA_G / (_ISA_L_K_PER_M * _ISA_R)
    return _ISA_P0_PA * (temp_k / _ISA_T0_K) ** exponent


def _cas_to_tas_mps(
    cas_mps: float, *, pressure_pa: float, temp_k: float
) -> float:
    """Calibrated airspeed to TAS using density ratio."""
    rho = pressure_pa / (_ISA_R * temp_k)
    sigma = rho / _ISA_RHO0
    if sigma <= 0.0:
        return cas_mps
    return cas_mps / math.sqrt(sigma)


def _mach_to_tas_mps(mach: float, temp_k: float) -> float:
    """Mach to TAS at static temperature *temp_k*."""
    return mach * math.sqrt(_ISA_GAMMA * _ISA_R * temp_k)


def _tas_to_gs_mps(
    tas_mps: float,
    heading_deg: float,
    wind_north: float,
    wind_east: float,
) -> float:
    """Groundspeed of TAS along *heading_deg* plus NED wind."""
    heading_rad = math.radians(heading_deg)
    north = tas_mps * math.cos(heading_rad) + wind_north
    east = tas_mps * math.sin(heading_rad) + wind_east
    return math.hypot(north, east)


def _wrap_heading_deg(heading_deg: float) -> float:
    """Wrap degrees into ``[0, 360)``."""
    return heading_deg % 360.0


def _unhealthy_sensor_faults(
    present: int, enabled: int, health: int
) -> tuple[FaultSnapshot, ...]:
    """SET faults for sensors that are present, enabled, and not healthy."""
    faults: list[FaultSnapshot] = []
    watched = present & enabled
    for bit, code, description in _SENSOR_BITS:
        if watched & bit and health & bit == 0:
            faults.append(
                FaultSnapshot(
                    fault_id=uuid5(_FAULT_NS, code),
                    fault_code=code,
                    fault_state="SET",
                    fault_description=description,
                )
            )
    return tuple(faults)


def _battery_duration_s(
    *,
    time_remaining_s: float | None,
    battery_remaining: int | None,
    current_battery_a: float | None,
    current_consumed_mah: float | None,
) -> float | None:
    """Seconds left from ``time_remaining``, else consumed / current.

    Capacity is inferred from consumed mAh and remaining percent.
    Returns ``None`` when neither source is usable. Does not invent
    a pack size.
    """
    if time_remaining_s is not None and time_remaining_s > 0.0:
        return time_remaining_s
    if (
        battery_remaining is None
        or current_battery_a is None
        or current_consumed_mah is None
    ):
        return None
    if battery_remaining <= 0 or current_battery_a <= 0.0:
        return None
    used_frac = 1.0 - (float(battery_remaining) / 100.0)
    if used_frac <= 0.0 or current_consumed_mah <= 0.0:
        return None
    capacity_mah = current_consumed_mah / used_frac
    remaining_mah = capacity_mah - current_consumed_mah
    if remaining_mah <= 0.0:
        return 0.0
    return remaining_mah / current_battery_a * 3.6


def _wind_ned(
    *,
    wind_north: float | None,
    wind_east: float | None,
    airspeed: float,
    vx_mps: float,
    vy_mps: float,
) -> tuple[float, float]:
    """WIND / WIND_COV, else GS minus TAS along track, else (0, 0)."""
    if wind_north is not None and wind_east is not None:
        return wind_north, wind_east
    gs = math.hypot(vx_mps, vy_mps)
    if airspeed > 0.1 and gs > 0.1:
        track = math.atan2(vy_mps, vx_mps)
        return (
            vx_mps - airspeed * math.cos(track),
            vy_mps - airspeed * math.sin(track),
        )
    return 0.0, 0.0


_QNH_ACK_TIMEOUT_S = 5.0


def _horiz_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    chord = (
        math.sin(dp / 2.0) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    )
    return 2.0 * _EARTH_M * math.asin(min(1.0, math.sqrt(chord)))


def _enu_m(
    lat0: float, lon0: float, lat: float, lon: float
) -> tuple[float, float]:
    """East/north meters from ``(lat0, lon0)``."""
    lat0_rad = math.radians(lat0)
    east = math.radians(lon - lon0) * _EARTH_M * math.cos(lat0_rad)
    north = math.radians(lat - lat0) * _EARTH_M
    return east, north


def advance_mission_waypoints(
    waypoints: tuple[Waypoint, ...],
    here: tuple[float, float],
    *,
    capture_m: float = DEFAULT_PATH_CLEARANCE_M,
) -> tuple[Waypoint, ...]:
    """Drop prefix WPs already captured or behind the vehicle toward the goal.

    A replacement route often starts at the current pose, then a point
    behind the aircraft. Uploading that prefix makes PX4 turn around.
    Keep the goal.
    """
    if len(waypoints) <= 1:
        return waypoints
    goal = waypoints[-1]
    ge, gn = _enu_m(here[0], here[1], goal.latitude_deg, goal.longitude_deg)
    kept = list(waypoints)
    while len(kept) > 1:
        we, wn = _enu_m(
            here[0], here[1], kept[0].latitude_deg, kept[0].longitude_deg
        )
        captured = (
            _horiz_m(
                here[0], here[1], kept[0].latitude_deg, kept[0].longitude_deg
            )
            < capture_m
        )
        behind = (we * ge + wn * gn) < 0.0
        if captured or behind:
            kept.pop(0)
            continue
        break
    return tuple(kept)


DEFAULT_MAVLINK_URL = "udpin:127.0.0.1:14540"
_HEARTBEAT_STALE_S = 10.0
_OFFBOARD_HZ = 10.0
_OFFBOARD_PRIME = 5


@dataclass
class _ResolvedHsa:
    """Live offboard vector (NED yaw / groundspeed / AGL)."""

    heading_deg: float
    speed_mps: float
    rel_alt_m: float


@dataclass
class _MavCache:
    """Latest telemetry fields (SI units where noted)."""

    last_heartbeat_mono: float = 0.0
    lat_deg: float = 0.0
    lon_deg: float = 0.0
    alt_m: float = 0.0
    relative_alt_m: float = 0.0
    vx_mps: float = 0.0
    vy_mps: float = 0.0
    vz_mps: float = 0.0
    roll_rad: float = 0.0
    pitch_rad: float = 0.0
    yaw_rad: float = 0.0
    airspeed_mps: float = 0.0
    groundspeed_mps: float = 0.0
    heading_deg: float = 0.0
    compass_heading_deg: float | None = None
    ekf_yaw_deg: float | None = None
    wind_north_mps: float | None = None
    wind_east_mps: float | None = None
    static_pressure_pa: float | None = None
    temperature_k: float | None = None
    battery_remaining: int | None = None
    time_remaining_s: float | None = None
    current_battery_a: float | None = None
    current_consumed_mah: float | None = None
    sensors_present: int = 0
    sensors_enabled: int = 0
    sensors_health: int = 0
    system_status: int = 0
    armed: bool = False
    base_mode: int = 0


class Px4MavlinkAdapter(PlatformPort):
    """Live PX4 vehicle: heartbeat/TSPI in, waypoint missions out.

    ``snapshot`` is ``AVAILABLE`` while HEARTBEAT or
    ``GLOBAL_POSITION_INT`` is fresher than 10 s; otherwise
    ``TEMPORARILY_UNAVAILABLE`` / ``PX4_LINK_DOWN``. Accepted
    ``WAYPOINT_FOLLOWING`` uploads a mission (NAV_TAKEOFF as item 0
    unless already airborne), arms, starts MISSION, and waits for
    climb. Activity UPDATE reuses that airborne replace and keeps
    the live ``activity_id``. A-GRA ``Point2D`` altitude is HAE; PX4
    items are relative to home. Completes when
    ``MISSION_ITEM_REACHED`` hits the last waypoint.

    ``HSA_CSA`` streams an offboard heading/speed/altitude hold.
    Leftover speed / heading / altitude refs convert onto that
    NED vector. Waypoint paths use the 10–500 m AGL envelope; HSA
    uses 0–500 m AGL so a hold at home HAE is inside the advertised
    bound. Both compare on a 0.1 m grid.
    ``apply_system_management`` writes ``SENS_BARO_QNH`` and the local
    TSPI snapshot.
    """

    def __init__(
        self,
        connection_url: str | None = None,
        *,
        autoconnect: bool = True,
        heartbeat_timeout_s: float | None = None,
        connection: Any | None = None,
        takeoff_alt_m: float = 30.0,
        path_clearance_m: float | None = None,
        min_rel_alt_m: float | None = None,
        max_rel_alt_m: float | None = None,
    ) -> None:
        self.connection_url = connection_url or os.environ.get(
            "PX4_MAVLINK_URL", DEFAULT_MAVLINK_URL
        )
        self._heartbeat_timeout_s = (
            heartbeat_timeout_s
            if heartbeat_timeout_s is not None
            else float(os.environ.get("PX4_HEARTBEAT_TIMEOUT_S", "10"))
        )
        self._path_clearance_m = (
            float(path_clearance_m)
            if path_clearance_m is not None
            else float(
                os.environ.get(
                    "PX4_PATH_CLEARANCE_M", str(DEFAULT_PATH_CLEARANCE_M)
                )
            )
        )
        self._takeoff_alt_m = takeoff_alt_m
        self._min_rel_alt_m = (
            float(min_rel_alt_m)
            if min_rel_alt_m is not None
            else float(
                os.environ.get("PX4_MIN_REL_ALT_M", str(DEFAULT_MIN_REL_ALT_M))
            )
        )
        self._max_rel_alt_m = (
            float(max_rel_alt_m)
            if max_rel_alt_m is not None
            else float(
                os.environ.get("PX4_MAX_REL_ALT_M", str(DEFAULT_MAX_REL_ALT_M))
            )
        )
        self._conn: Any | None = connection
        self._offer = ControlOffer(
            capability_types=(
                "WAYPOINT_FOLLOWING",
                "HSA_CSA",
                "CURVE_FOLLOWING",
            ),
            capability_label="px4-flight-capability",
        )
        self._activity: FlightActivitySnapshot | None = None
        self._commands: dict[UUID, str] = {}
        self._pending_updates: list[tuple[UUID, CommandResult]] = []
        self._active_command_id: UUID | None = None
        self._mission_last_seq: int | None = None
        self._service_id = uuid4()
        self._subsystem_id = uuid4()
        self._fault_id = uuid4()
        self._component_id = uuid4()
        self._started = time.monotonic()
        self._cache = _MavCache()
        self._lock = threading.Lock()
        self._io_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._offboard_stop = threading.Event()
        self._offboard_thread: threading.Thread | None = None
        self._hsa_live: _ResolvedHsa | None = None
        self._home_hae_frozen: float | None = None
        self._kollsman_hpa = 1013.25
        if autoconnect and self._conn is None:
            self.connect()

    def connect(self) -> None:
        """Open MAVLink, wait for HEARTBEAT, apply nav params, start the reader.

        pymavlink is imported here so a stub-only install can still
        import this module. Raises ``ImportError`` without the extra,
        ``TimeoutError`` if no heartbeat arrives.
        """
        if self._conn is not None:
            return
        try:
            # Optional dependency: keep import lazy so stub installs work.
            # pylint: disable-next=import-outside-toplevel
            from pymavlink import mavutil
        except ImportError as exc:
            raise ImportError(
                "PX4 backend requires pymavlink; "
                "install with pip install -e '.[px4]'"
            ) from exc
        LOGGER.info("Connecting to PX4 at %s", self.connection_url)
        self._conn = mavutil.mavlink_connection(self.connection_url)
        msg = self._conn.wait_heartbeat(timeout=self._heartbeat_timeout_s)
        if msg is None:
            self.close()
            raise TimeoutError(
                f"No HEARTBEAT from {self.connection_url} within "
                f"{self._heartbeat_timeout_s}s"
            )
        with self._lock:
            self._cache.last_heartbeat_mono = time.monotonic()
        LOGGER.info(
            "PX4 heartbeat system=%s component=%s",
            self._conn.target_system,
            self._conn.target_component,
        )
        self._apply_nav_params()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._reader_loop,
            name="open-vi-px4-mavlink",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        """Stop reader and offboard threads; close the MAVLink connection."""
        self._stop_offboard()
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        conn = self._conn
        self._conn = None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # pylint: disable=broad-exception-caught
                LOGGER.debug("PX4 connection close failed", exc_info=True)

    def snapshot(self) -> PlatformSnapshot:
        """Waypoint, HSA, and curve offer plus link-based readiness."""
        if self._link_ok():
            readiness = ControlReadiness(
                available=True,
                availability="AVAILABLE",
            )
        else:
            readiness = ControlReadiness(
                available=False,
                availability="TEMPORARILY_UNAVAILABLE",
                reason="PX4_LINK_DOWN",
            )
        offer = ControlOffer(
            capability_types=self._offer.capability_types,
            capability_label=self._offer.capability_label,
            accepted_interfaces=self._offer.accepted_interfaces,
            waypoint_profile=self._rel_profile(self._min_rel_alt_m),
            hsa_profile=self._rel_profile(0.0),
            curve_profile=self._rel_profile(self._min_rel_alt_m),
        )
        return PlatformSnapshot(offer=offer, readiness=readiness)

    def _rel_profile(self, min_rel_m: float) -> FlightModeProfile:
        """AGL envelope, or HAE once home is known."""
        home = self._home_hae_m()
        if home is None:
            return FlightModeProfile(
                min_altitude_m=min_rel_m,
                max_altitude_m=self._max_rel_alt_m,
                altitude_ref="AGL",
            )
        return FlightModeProfile(
            min_altitude_m=home + min_rel_m,
            max_altitude_m=home + self._max_rel_alt_m,
            altitude_ref="WGS_HAE",
        )

    def submit_flight_command(self, cmd: FlightCommandRequest) -> CommandResult:
        """Accept waypoint, curve, or HSA NEW when idle, UPDATE, or CANCEL.

        Rejects when the link is down, Capability NEW arrives while an
        activity is live, Activity is not UPDATE against the live id,
        or the mode is unsupported. Waypoint and curve accept upload a
        mission. HSA streams an offboard hold until CANCEL. Path
        completion is later, via :meth:`poll_command_updates`.
        """
        snap = self.snapshot()
        if not snap.readiness.available:
            return CommandResult(
                processing_state="REJECTED",
                reason="CAPABILITY_UNAVAILABLE",
                reason_description="PX4 link not available",
            )
        if cmd.choice == "Activity":
            return self._submit_activity(cmd)
        if cmd.command_state == "CANCEL":
            if cmd.command_id in self._commands:
                self._stop_offboard()
                self._hold_if_linked()
                with self._lock:
                    self._commands[cmd.command_id] = "CANCELED"
                    self._activity = None
                    if self._active_command_id == cmd.command_id:
                        self._active_command_id = None
                        self._mission_last_seq = None
                    self._pending_updates = [
                        item
                        for item in self._pending_updates
                        if item[0] != cmd.command_id
                    ]
                return CommandResult(processing_state="CANCELED")
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description="Unknown command id for CANCEL",
            )
        if cmd.command_state != "NEW":
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description=(
                    "Capability commands require CommandState NEW or CANCEL"
                ),
            )
        with self._lock:
            live = self._activity
        if is_live_activity(live):
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description=(
                    "Capability NEW is not allowed while an activity "
                    "is live; use Activity UPDATE"
                ),
            )
        rejected = self._execute_or_reject(cmd)
        if rejected is not None:
            return rejected
        activity_id = uuid4()
        with self._lock:
            self._activity = FlightActivitySnapshot(
                activity_id=activity_id,
                capability_id=cmd.capability_id,
                activity_state="ACTIVE_UNCONSTRAINED",
                interactive=True,
            )
            self._commands[cmd.command_id] = "ACCEPTED"
            self._active_command_id = cmd.command_id
        return CommandResult(
            processing_state="ACCEPTED",
            activity_id=activity_id,
            new_activity=True,
        )

    def _submit_activity(self, cmd: FlightCommandRequest) -> CommandResult:
        """Replace the live path; keep ``activity_id``.

        Later ``COMPLETED`` is for this UPDATE command, not the original NEW.
        """
        if cmd.command_state != "UPDATE":
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description=(
                    "Activity commands require CommandState UPDATE"
                ),
            )
        with self._lock:
            live = self._activity
        if not is_live_activity(live) or cmd.activity_id != live.activity_id:
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description="Unknown or idle ActivityID",
            )
        rejected = self._execute_or_reject(cmd)
        if rejected is not None:
            return rejected
        with self._lock:
            self._commands[cmd.command_id] = "ACCEPTED"
            self._active_command_id = cmd.command_id
        return CommandResult(
            processing_state="ACCEPTED",
            activity_id=live.activity_id,
            new_activity=False,
        )

    def _execute_or_reject(
        self, cmd: FlightCommandRequest
    ) -> CommandResult | None:
        """Fly waypoints, a sampled curve, or HSA, or return a reject.

        ``None`` means the vehicle ran.
        """
        if cmd.mode == "HSA_CSA":
            return self._execute_hsa_or_reject(cmd)
        if cmd.mode == "CURVE_FOLLOWING":
            return self._execute_curve_or_reject(cmd)
        if cmd.mode != "WAYPOINT_FOLLOWING":
            return CommandResult(
                processing_state="REJECTED",
                reason="CAPABILITY_UNAVAILABLE",
                reason_description=(
                    "PX4 adapter accepts WAYPOINT_FOLLOWING, "
                    f"CURVE_FOLLOWING, and HSA_CSA; got {cmd.mode}"
                ),
                validation_results=("CAPABILITY_NOT_SUPPORTED",),
            )
        rejected = validate_waypoint_path(
            cmd.waypoints,
            min_rel_alt_m=self._min_rel_alt_m,
            max_rel_alt_m=self._max_rel_alt_m,
            home_hae_m=self._home_hae_m(),
        )
        if rejected is not None:
            return rejected
        self._stop_offboard()
        try:
            self._execute_waypoint_following(cmd.waypoints)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            LOGGER.exception("PX4 waypoint execution failed")
            return CommandResult(
                processing_state="REJECTED",
                reason="STATE_OR_SETTINGS",
                reason_description=f"Waypoint execution failed: {exc}",
            )
        return None

    def _execute_curve_or_reject(
        self, cmd: FlightCommandRequest
    ) -> CommandResult | None:
        """Sample the NURBS to waypoints and fly that mission."""
        curve = cmd.curve
        altitude_m = self._curve_altitude_m(curve)
        rejected = validate_curve_following(
            curve,
            altitude_m=altitude_m,
            min_rel_alt_m=self._min_rel_alt_m,
            max_rel_alt_m=self._max_rel_alt_m,
            home_hae_m=self._home_hae_m(),
        )
        if rejected is not None:
            return rejected
        if curve is None:
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description="CURVE_FOLLOWING requires CurveSegments",
                validation_results=("INVALID_WAYPOINT",),
            )
        waypoints = sample_curve_waypoints(curve, altitude_m=altitude_m)
        self._stop_offboard()
        try:
            self._execute_waypoint_following(waypoints)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            LOGGER.exception("PX4 curve execution failed")
            return CommandResult(
                processing_state="REJECTED",
                reason="STATE_OR_SETTINGS",
                reason_description=f"Curve execution failed: {exc}",
            )
        return None

    def _curve_altitude_m(self, curve: CurveFollowingSetpoint | None) -> float:
        """HAE for every sample: center, current, or home + takeoff."""
        if curve is not None and curve.center_alt_m is not None:
            return float(curve.center_alt_m)
        if self._relative_alt_m() >= 2.0:
            return float(self.get_vehicle_state().altitude_m)
        home = self._home_hae_m()
        if home is not None:
            return home + self._takeoff_alt_m
        return self._takeoff_alt_m

    def _execute_hsa_or_reject(
        self, cmd: FlightCommandRequest
    ) -> CommandResult | None:
        """Start or replace an HSA offboard hold, or return a reject."""
        rejected = validate_hsa_setpoint(
            cmd.hsa,
            min_rel_alt_m=0.0,
            max_rel_alt_m=self._max_rel_alt_m,
            home_hae_m=self._home_hae_m(),
        )
        if rejected is not None:
            return rejected
        try:
            self._execute_hsa_csa(cmd.hsa or HsaCsaSetpoint())
        except Exception as exc:  # pylint: disable=broad-exception-caught
            LOGGER.exception("PX4 HSA_CSA execution failed")
            return CommandResult(
                processing_state="REJECTED",
                reason="STATE_OR_SETTINGS",
                reason_description=f"HSA_CSA execution failed: {exc}",
            )
        return None

    def _execute_hsa_csa(self, hsa: HsaCsaSetpoint) -> None:
        """Hold or replace an offboard heading/speed/altitude vector."""
        live = self._resolve_hsa(hsa)
        already = (
            self._offboard_thread is not None
            and self._offboard_thread.is_alive()
        )
        with self._lock:
            self._hsa_live = live
            self._mission_last_seq = None
        if already:
            LOGGER.info(
                "PX4 HSA_CSA setpoint updated hdg=%.1f spd=%.1f alt=%.1f",
                live.heading_deg,
                live.speed_mps,
                live.rel_alt_m,
            )
            return
        airborne = self._relative_alt_m() >= 2.0
        try:
            with self._io_lock:
                if airborne:
                    self._hold_locked()
                self._prime_offboard_locked()
                if not self._set_mode_locked("OFFBOARD"):
                    raise RuntimeError("PX4 OFFBOARD mode not available")
                self._arm_locked(force=True)
                if not airborne:
                    self._wait_airborne_locked(live.rel_alt_m)
            self._start_offboard_thread()
        except Exception:
            self._stop_offboard()
            raise
        LOGGER.info(
            "PX4 HSA_CSA offboard hdg=%.1f spd=%.1f alt=%.1f",
            live.heading_deg,
            live.speed_mps,
            live.rel_alt_m,
        )

    def _resolve_hsa(self, hsa: HsaCsaSetpoint) -> _ResolvedHsa:
        """Fill omitted axes from telemetry and leftover-ref conversions.

        Magnetic heading needs EKF yaw and compass. TAS / CAS / Mach
        become groundspeed via wind (message, estimate, or 0).
        MSL and barometric altitude use the same home freeze as HAE.
        On the ground, climb uses takeoff altitude.
        """
        with self._lock:
            heading = self._cache.heading_deg
            speed = self._cache.groundspeed_mps
            rel = self._cache.relative_alt_m
            compass = self._cache.compass_heading_deg
            ekf_yaw = self._cache.ekf_yaw_deg
            wind_n = self._cache.wind_north_mps
            wind_e = self._cache.wind_east_mps
            airspeed = self._cache.airspeed_mps
            vx_mps = self._cache.vx_mps
            vy_mps = self._cache.vy_mps
            alt_amsl = self._cache.alt_m
            temp_k = self._cache.temperature_k
            pressure_pa = self._cache.static_pressure_pa
        if hsa.heading_deg is not None:
            heading = self._true_heading_deg(
                hsa.heading_deg,
                hsa.heading_ref,
                compass=compass,
                ekf_yaw=ekf_yaw,
            )
        if hsa.mach is not None or hsa.speed_mps is not None:
            speed = self._hsa_groundspeed_mps(
                hsa,
                heading_deg=heading,
                wind_north=wind_n,
                wind_east=wind_e,
                airspeed=airspeed,
                vx_mps=vx_mps,
                vy_mps=vy_mps,
                alt_amsl=alt_amsl,
                temp_k=temp_k,
                pressure_pa=pressure_pa,
            )
        if hsa.altitude_m is not None:
            if hsa.altitude_ref in {
                "WGS_HAE",
                "MSL",
                "ALTITUDE_BAROMETRIC",
            }:
                home = self._home_hae_m()
                if home is not None:
                    rel = float(hsa.altitude_m) - home
                else:
                    rel = float(hsa.altitude_m)
            else:
                rel = float(hsa.altitude_m)
        if rel < 2.0:
            rel = self._takeoff_alt_m
        return _ResolvedHsa(
            heading_deg=heading,
            speed_mps=speed,
            rel_alt_m=rel,
        )

    def _true_heading_deg(
        self,
        heading_deg: float,
        heading_ref: str | None,
        *,
        compass: float | None,
        ekf_yaw: float | None,
    ) -> float:
        """Commanded heading in true degrees.

        ``MAGNETIC_NORTH`` uses EKF yaw minus compass. Missing either
        heading raises so the command is ``STATE_OR_SETTINGS``.
        """
        del self
        if heading_ref != "MAGNETIC_NORTH":
            return _wrap_heading_deg(heading_deg)
        if compass is None or ekf_yaw is None:
            raise RuntimeError(
                "HSA magnetic heading needs EKF yaw and compass heading"
            )
        declination = ekf_yaw - compass
        return _wrap_heading_deg(heading_deg + declination)

    def _hsa_groundspeed_mps(
        self,
        hsa: HsaCsaSetpoint,
        *,
        heading_deg: float,
        wind_north: float | None,
        wind_east: float | None,
        airspeed: float,
        vx_mps: float,
        vy_mps: float,
        alt_amsl: float,
        temp_k: float | None,
        pressure_pa: float | None,
    ) -> float:
        """Commanded speed as groundspeed for the offboard hold."""
        del self
        if hsa.mach is not None:
            tas = _mach_to_tas_mps(
                hsa.mach, temp_k or _isa_temperature_k(alt_amsl)
            )
        elif hsa.speed_ref == "CALIBRATED_AIRSPEED":
            tas = _cas_to_tas_mps(
                float(hsa.speed_mps or 0.0),
                pressure_pa=pressure_pa or _isa_pressure_pa(alt_amsl),
                temp_k=temp_k or _isa_temperature_k(alt_amsl),
            )
        elif hsa.speed_ref == "TRUE_AIRSPEED":
            tas = float(hsa.speed_mps or 0.0)
        else:
            return float(hsa.speed_mps or 0.0)
        north, east = _wind_ned(
            wind_north=wind_north,
            wind_east=wind_east,
            airspeed=airspeed,
            vx_mps=vx_mps,
            vy_mps=vy_mps,
        )
        return _tas_to_gs_mps(tas, heading_deg, north, east)

    def _start_offboard_thread(self) -> None:
        """Stream setpoints at ``_OFFBOARD_HZ`` until stop."""
        self._offboard_stop.clear()
        self._offboard_thread = threading.Thread(
            target=self._offboard_loop,
            name="open-vi-px4-offboard",
            daemon=True,
        )
        self._offboard_thread.start()

    def _stop_offboard(self) -> None:
        """Join the offboard writer and clear the live vector."""
        self._offboard_stop.set()
        thread = self._offboard_thread
        if thread is not None:
            thread.join(timeout=2.0)
            self._offboard_thread = None
        with self._lock:
            self._hsa_live = None

    def _hold_if_linked(self) -> None:
        """LOITER/HOLD when a link exists. Best-effort."""
        if self._conn is None:
            return
        with self._io_lock:
            self._hold_locked()

    def _offboard_loop(self) -> None:
        """Send LOCAL_NED setpoints until ``_offboard_stop``."""
        period = 1.0 / _OFFBOARD_HZ
        while not self._offboard_stop.wait(period):
            try:
                with self._io_lock:
                    self._send_offboard_setpoint_locked()
            except Exception:  # pylint: disable=broad-exception-caught
                LOGGER.exception("PX4 offboard setpoint failed")
                return

    def _prime_offboard_locked(self) -> None:
        """Send a few setpoints before switching OFFBOARD."""
        for _ in range(_OFFBOARD_PRIME):
            self._send_offboard_setpoint_locked()

    def _send_offboard_setpoint_locked(self) -> None:
        """One SET_POSITION_TARGET_LOCAL_NED. Holds ``_io_lock``."""
        # pylint: disable-next=import-outside-toplevel
        from pymavlink import mavutil

        with self._lock:
            live = self._hsa_live
        if live is None:
            return
        conn = self._require_conn()
        heading_rad = math.radians(live.heading_deg)
        vx = live.speed_mps * math.cos(heading_rad)
        vy = live.speed_mps * math.sin(heading_rad)
        z_down = -live.rel_alt_m
        ignore = (
            mavutil.mavlink.POSITION_TARGET_TYPEMASK_X_IGNORE
            | mavutil.mavlink.POSITION_TARGET_TYPEMASK_Y_IGNORE
            | mavutil.mavlink.POSITION_TARGET_TYPEMASK_VZ_IGNORE
            | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AX_IGNORE
            | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AY_IGNORE
            | mavutil.mavlink.POSITION_TARGET_TYPEMASK_AZ_IGNORE
            | mavutil.mavlink.POSITION_TARGET_TYPEMASK_YAW_RATE_IGNORE
        )
        conn.mav.set_position_target_local_ned_send(
            0,
            conn.target_system,
            conn.target_component,
            mavutil.mavlink.MAV_FRAME_LOCAL_NED,
            ignore,
            0.0,
            0.0,
            z_down,
            vx,
            vy,
            0.0,
            0.0,
            0.0,
            0.0,
            heading_rad,
            0.0,
        )

    def poll_command_updates(self) -> list[tuple[UUID, CommandResult]]:
        """Drain terminal states queued by ``MISSION_ITEM_REACHED``."""
        with self._lock:
            updates = list(self._pending_updates)
            self._pending_updates.clear()
            return updates

    def active_flight_activity(self) -> FlightActivitySnapshot | None:
        """Current mission activity, or ``None`` if idle or canceled."""
        return self._activity

    def get_vehicle_state(self) -> TspiSnapshot:
        """Map the MAVLink cache into ``TspiSnapshot`` (degrees, NED, fuel)."""
        with self._lock:
            c = self._cache
            fuel = 85.0
            if c.battery_remaining is not None:
                fuel = float(c.battery_remaining)
            heading_rad = math.radians(c.heading_deg)
            duration_s = _battery_duration_s(
                time_remaining_s=c.time_remaining_s,
                battery_remaining=c.battery_remaining,
                current_battery_a=c.current_battery_a,
                current_consumed_mah=c.current_consumed_mah,
            )
            return TspiSnapshot(
                latitude_deg=c.lat_deg,
                longitude_deg=c.lon_deg,
                altitude_m=c.alt_m,
                north_speed_mps=c.vx_mps,
                east_speed_mps=c.vy_mps,
                down_speed_mps=c.vz_mps,
                yaw_rad=c.yaw_rad,
                pitch_rad=c.pitch_rad,
                roll_rad=c.roll_rad,
                indicated_baro_altitude_m=c.alt_m,
                kollsman_hpa=self._kollsman_hpa,
                true_airspeed_mps=c.airspeed_mps,
                calibrated_airspeed_mps=c.airspeed_mps,
                fuel_percent=fuel,
                fuel_duration_s=duration_s,
                magnetic_heading_rad=heading_rad,
                component_id=self._component_id,
                component_label="px4",
                component_state="OPERATIONAL",
            )

    def get_service_status(self) -> ServiceStatusSnapshot:
        """VI service heartbeat fields for this adapter process."""
        secs = max(0, int(time.monotonic() - self._started))
        return ServiceStatusSnapshot(
            service_id=self._service_id,
            service_label="open-vi-px4",
            time_up=f"PT{secs}S",
        )

    def get_subsystem_status(self) -> SubsystemStatusSnapshot:
        """Flight-subsystem row. ``DEGRADED`` when BIT or the link fails."""
        state = "DEGRADED" if self._bit_failed() else "OPERATE"
        return SubsystemStatusSnapshot(
            subsystem_id=self._subsystem_id,
            subsystem_label="flight",
            subsystem_state=state,
            model="px4",
            software_version="sitl",
        )

    def get_faults(self) -> tuple[FaultSnapshot, ...]:
        """Periodic BIT from SYS_STATUS, or link-down / cleared sentinel."""
        if not self._link_ok():
            return (
                FaultSnapshot(
                    fault_id=uuid5(_FAULT_NS, "PX4_LINK_DOWN"),
                    fault_code="PX4_LINK_DOWN",
                    fault_state="SET",
                    fault_description="PX4 MAVLink link is down",
                ),
            )
        with self._lock:
            faults = _unhealthy_sensor_faults(
                self._cache.sensors_present,
                self._cache.sensors_enabled,
                self._cache.sensors_health,
            )
        if faults:
            return faults
        return (FaultSnapshot(fault_id=self._fault_id),)

    def _bit_failed(self) -> bool:
        """True when the link is down or a watched sensor is unhealthy."""
        if not self._link_ok():
            return True
        with self._lock:
            return bool(
                _unhealthy_sensor_faults(
                    self._cache.sensors_present,
                    self._cache.sensors_enabled,
                    self._cache.sensors_health,
                )
            )

    def apply_system_management(self, *, qnh_kpa: float | None = None) -> str:
        """Write QNH to PX4 and the local TSPI snapshot.

        *qnh_kpa* is converted to hPa (×10) and sent as
        ``SENS_BARO_QNH``. Link down or a missing PARAM_VALUE is
        ``REJECTED``.
        """
        if qnh_kpa is None:
            return "COMPLETED"
        hpa = float(qnh_kpa) * 10.0
        if not self._link_ok():
            return "REJECTED"
        try:
            self._set_qnh_hpa(hpa)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            LOGGER.warning("PX4 QNH PARAM_SET failed: %s", exc)
            return "REJECTED"
        self._kollsman_hpa = hpa
        return "COMPLETED"

    def _set_qnh_hpa(self, hpa: float) -> None:
        """PARAM_SET ``SENS_BARO_QNH`` and wait for PARAM_VALUE."""
        # pylint: disable-next=import-outside-toplevel
        from pymavlink import mavutil

        conn = self._require_conn()
        name = _QNH_PARAM.encode("ascii")
        with self._io_lock:
            conn.mav.param_set_send(
                conn.target_system,
                conn.target_component,
                name,
                float(hpa),
                mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
            )
            deadline = time.monotonic() + _QNH_ACK_TIMEOUT_S
            while time.monotonic() < deadline:
                msg = conn.recv_match(
                    type="PARAM_VALUE", blocking=True, timeout=1.0
                )
                if msg is None:
                    continue
                param_id = getattr(msg, "param_id", b"")
                if isinstance(param_id, bytes):
                    param_id = param_id.split(b"\x00", 1)[0].decode(
                        "ascii", errors="replace"
                    )
                if str(param_id).strip("\x00") == _QNH_PARAM:
                    return
        raise TimeoutError("Timed out waiting for SENS_BARO_QNH")

    def _link_ok(self) -> bool:
        """True when a HEARTBEAT or position update is newer than 10 s."""
        if self._conn is None:
            return False
        with self._lock:
            last = self._cache.last_heartbeat_mono
        if last <= 0.0:
            return False
        return (time.monotonic() - last) <= _HEARTBEAT_STALE_S

    def _reader_loop(self) -> None:
        """Drain MAVLink into :meth:`_ingest` until ``close``."""
        assert self._conn is not None
        while not self._stop.wait(0.01):
            try:
                with self._io_lock:
                    msg = self._conn.recv_match(blocking=False)
            except Exception:  # pylint: disable=broad-exception-caught
                LOGGER.exception("PX4 recv_match failed")
                continue
            if msg is None:
                continue
            self._ingest(msg)

    def _ingest(self, msg: Any) -> None:
        """Update the telemetry cache.

        Completes the mission when the last waypoint is reached.
        """
        mtype = msg.get_type()
        with self._lock:
            if mtype == "HEARTBEAT":
                self._cache.last_heartbeat_mono = time.monotonic()
                self._cache.system_status = int(
                    getattr(msg, "system_status", 0)
                )
                base_mode = int(getattr(msg, "base_mode", 0))
                self._cache.base_mode = base_mode
                # MAV_MODE_FLAG_SAFETY_ARMED = 128
                self._cache.armed = bool(base_mode & 128)
            elif mtype == "GLOBAL_POSITION_INT":
                self._cache.last_heartbeat_mono = time.monotonic()
                self._cache.lat_deg = msg.lat / 1e7
                self._cache.lon_deg = msg.lon / 1e7
                self._cache.alt_m = msg.alt / 1000.0
                self._cache.relative_alt_m = (
                    float(getattr(msg, "relative_alt", 0)) / 1000.0
                )
                self._cache.vx_mps = msg.vx / 100.0
                self._cache.vy_mps = msg.vy / 100.0
                self._cache.vz_mps = msg.vz / 100.0
                hdg_cdeg = float(msg.hdg)
                if hdg_cdeg < _HDG_UNKNOWN_CDEG:
                    heading = hdg_cdeg / 100.0
                    self._cache.heading_deg = heading
                    self._cache.compass_heading_deg = heading
            elif mtype == "ATTITUDE":
                self._cache.last_heartbeat_mono = time.monotonic()
                self._cache.roll_rad = float(msg.roll)
                self._cache.pitch_rad = float(msg.pitch)
                self._cache.yaw_rad = float(msg.yaw)
                self._cache.ekf_yaw_deg = math.degrees(float(msg.yaw))
            elif mtype == "VFR_HUD":
                airspeed = float(msg.airspeed)
                groundspeed = float(msg.groundspeed)
                self._cache.airspeed_mps = (
                    airspeed if math.isfinite(airspeed) else 0.0
                )
                self._cache.groundspeed_mps = (
                    groundspeed if math.isfinite(groundspeed) else 0.0
                )
                heading = float(msg.heading)
                self._cache.heading_deg = heading
                self._cache.compass_heading_deg = heading
            elif mtype == "WIND_COV":
                self._cache.wind_north_mps = float(msg.wind_x)
                self._cache.wind_east_mps = float(msg.wind_y)
            elif mtype == "WIND":
                coming_from = math.radians(float(msg.direction))
                wind_speed = float(msg.speed)
                self._cache.wind_north_mps = -wind_speed * math.cos(coming_from)
                self._cache.wind_east_mps = -wind_speed * math.sin(coming_from)
            elif mtype == "SCALED_PRESSURE":
                press_pa = float(msg.press_abs) * 100.0
                if math.isfinite(press_pa) and press_pa > 0.0:
                    self._cache.static_pressure_pa = press_pa
                temp_k = float(getattr(msg, "temperature", 0.0)) / 100.0
                temp_k += 273.15
                if _TEMP_MIN_K < temp_k < _TEMP_MAX_K:
                    self._cache.temperature_k = temp_k
            elif mtype == "SYS_STATUS":
                rem = int(getattr(msg, "battery_remaining", -1))
                self._cache.battery_remaining = rem if rem >= 0 else None
                self._cache.sensors_present = int(
                    getattr(msg, "onboard_control_sensors_present", 0)
                )
                self._cache.sensors_enabled = int(
                    getattr(msg, "onboard_control_sensors_enabled", 0)
                )
                self._cache.sensors_health = int(
                    getattr(msg, "onboard_control_sensors_health", 0)
                )
            elif mtype == "BATTERY_STATUS":
                rem = int(getattr(msg, "battery_remaining", -1))
                if rem >= 0:
                    self._cache.battery_remaining = rem
                remaining_s = float(getattr(msg, "time_remaining", 0))
                if math.isfinite(remaining_s) and remaining_s > 0.0:
                    self._cache.time_remaining_s = remaining_s
                current_ca = float(getattr(msg, "current_battery", -1))
                if math.isfinite(current_ca) and current_ca >= 0.0:
                    self._cache.current_battery_a = current_ca / 100.0
                consumed = float(getattr(msg, "current_consumed", -1))
                if math.isfinite(consumed) and consumed >= 0.0:
                    self._cache.current_consumed_mah = consumed
            elif mtype == "MISSION_ITEM_REACHED":
                seq = int(getattr(msg, "seq", -1))
                self._maybe_complete_mission_locked(seq)

    def _maybe_complete_mission_locked(self, seq: int) -> None:
        """Queue ``COMPLETED`` when *seq* reaches the last uploaded waypoint.

        Caller must hold ``_lock``. No-op if nothing is active or *seq*
        is still short of ``_mission_last_seq``.
        """
        cid = self._active_command_id
        last = self._mission_last_seq
        if cid is None or last is None or seq < last:
            return
        if self._commands.get(cid) != "ACCEPTED":
            return
        self._commands[cid] = "COMPLETED"
        activity_id = None
        if self._activity is not None:
            activity_id = self._activity.activity_id
            self._activity = replace(self._activity, activity_state="COMPLETED")
        self._pending_updates.append(
            (
                cid,
                CommandResult(
                    processing_state="COMPLETED",
                    activity_id=activity_id,
                ),
            )
        )
        self._active_command_id = None
        self._mission_last_seq = None
        LOGGER.info("PX4 mission complete cmd=%s seq=%s", cid.hex, seq)

    def _home_hae_m(self) -> float | None:
        """Home HAE from GLOBAL_POSITION_INT: AMSL minus relative-to-home.

        The first fix is frozen so the advertised HAE envelope and the
        accept check use the same origin while GPS home jitters.
        """
        with self._lock:
            if self._home_hae_frozen is not None:
                return self._home_hae_frozen
            alt = self._cache.alt_m
            rel = self._cache.relative_alt_m
        if alt == 0.0 and rel == 0.0:
            return None
        home = alt - rel
        with self._lock:
            if self._home_hae_frozen is None:
                self._home_hae_frozen = home
            return self._home_hae_frozen

    def _mission_rel_alt_m(self, altitude_m: float | None) -> float:
        """A-GRA Point2D altitude is HAE; PX4 items are relative to home."""
        floor = self._takeoff_alt_m
        if altitude_m is None:
            return floor
        home = self._home_hae_m()
        if home is None:
            return max(floor, float(altitude_m))
        return max(floor, float(altitude_m) - home)

    def _flight_rel_alt_m(self) -> float:
        """One AGL for every mission item so PX4 3D capture can succeed.

        A later command may carry a different HAE. Flattening to current
        AGL keeps every item inside the vertical capture window.
        """
        rel = self._relative_alt_m()
        if rel >= 2.0:
            return rel
        return self._takeoff_alt_m

    def _apply_nav_params(self) -> None:
        """Set MC acceptance to this adapter's capture radius."""
        # pylint: disable-next=import-outside-toplevel
        from pymavlink import mavutil

        conn = self._conn
        if conn is None or not hasattr(conn.mav, "param_set_send"):
            return
        clearance = self._path_clearance_m
        for name, value in (
            ("NAV_ACC_RAD", clearance),
            ("NAV_MC_ALT_RAD", clearance),
        ):
            conn.mav.param_set_send(
                conn.target_system,
                conn.target_component,
                name.encode("ascii"),
                float(value),
                mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
            )
        LOGGER.info(
            "PX4 nav capture NAV_ACC_RAD=%.0f NAV_MC_ALT_RAD=%.0f",
            clearance,
            clearance,
        )

    def _execute_waypoint_following(
        self, waypoints: tuple[Waypoint, ...]
    ) -> None:
        """Upload mission, arm, start MISSION mode.

        A replacement while airborne must not restart NAV_TAKEOFF.
        Drop waypoints already under the vehicle and start at the next
        remaining item.
        """
        remaining = self._remaining_waypoints(waypoints)
        if len(remaining) < len(waypoints):
            LOGGER.info(
                "PX4 skipped %d prefix WPs (kept %d, capture=%.0fm)",
                len(waypoints) - len(remaining),
                len(remaining),
                self._path_clearance_m,
            )
        airborne = self._relative_alt_m() >= 2.0
        hold_alt = self._flight_rel_alt_m()
        rel_wps = tuple(
            Waypoint(
                latitude_deg=wp.latitude_deg,
                longitude_deg=wp.longitude_deg,
                altitude_m=hold_alt,
            )
            for wp in remaining
        )
        with self._io_lock:
            if airborne:
                self._hold_locked()
            last_seq = self._upload_waypoints_locked(
                rel_wps,
                takeoff_alt_m=hold_alt,
                include_takeoff=not airborne,
            )
            self._arm_locked(force=True)
            self._start_mission_locked()
            if not airborne:
                self._wait_airborne_locked(hold_alt)
        with self._lock:
            self._mission_last_seq = last_seq
        LOGGER.info(
            "PX4 waypoint mission executing (%s WPs, takeoff=%s last_seq=%s)",
            len(remaining),
            "skip" if airborne else f"{hold_alt:.1f}m",
            last_seq,
        )

    def _remaining_waypoints(
        self, waypoints: tuple[Waypoint, ...]
    ) -> tuple[Waypoint, ...]:
        """Drop prefix waypoints already under or behind the vehicle."""
        if not waypoints:
            return waypoints
        here = self._current_ll()
        if here is None:
            return waypoints
        return advance_mission_waypoints(
            waypoints, here, capture_m=self._path_clearance_m
        )

    def _current_ll(self) -> tuple[float, float] | None:
        """Cached lat/lon, or ``None`` before the first position."""
        with self._lock:
            lat = self._cache.lat_deg
            lon = self._cache.lon_deg
        if lat == 0.0 and lon == 0.0:
            return None
        return lat, lon

    def _hold_locked(self) -> None:
        """Leave MISSION before replacing items. Holds ``_io_lock``."""
        for name in ("HOLD", "AUTO.LOITER", "LOITER"):
            if self._set_mode_locked(name):
                LOGGER.info("PX4 hold before mission replace (%s)", name)
                return

    def _upload_waypoints_locked(
        self,
        waypoints: tuple[Waypoint, ...],
        *,
        takeoff_alt_m: float,
        include_takeoff: bool = True,
    ) -> int:
        """Upload mission items. Returns last seq. Holds ``_io_lock``."""
        # pylint: disable-next=import-outside-toplevel
        from pymavlink import mavutil

        conn = self._require_conn()
        mav = conn.mav
        target_system = conn.target_system
        target_component = conn.target_component
        # Standalone TAKEOFF mode sits at MIS_TAKEOFF_ALT. Embedding
        # NAV_TAKEOFF as item 0 then MISSION_START is the climb path.
        # Skip takeoff when already airborne.
        items: list[tuple[int, float, float, float]] = []
        if include_takeoff:
            first = waypoints[0]
            items.append(
                (
                    mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                    first.latitude_deg,
                    first.longitude_deg,
                    float(takeoff_alt_m),
                )
            )
        for wp in waypoints:
            items.append(
                (
                    mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                    wp.latitude_deg,
                    wp.longitude_deg,
                    float(wp.altitude_m if wp.altitude_m is not None else 50.0),
                )
            )
        if items:
            _, lat, lon, alt = items[-1]
            items.append(
                (mavutil.mavlink.MAV_CMD_NAV_LOITER_UNLIM, lat, lon, alt)
            )
        count = len(items)
        last_wp_seq = count - 2 if count >= 2 else count - 1
        mav.mission_count_send(target_system, target_component, count)
        frame = mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
        waypoint_cmd = mavutil.mavlink.MAV_CMD_NAV_WAYPOINT
        for seq, (command, lat, lon, alt) in enumerate(items):
            msg = conn.recv_match(
                type=["MISSION_REQUEST", "MISSION_REQUEST_INT"],
                blocking=True,
                timeout=5.0,
            )
            if msg is None:
                raise TimeoutError(f"No MISSION_REQUEST for seq {seq}")
            is_last = seq == count - 1
            accept_m = (
                self._path_clearance_m if command == waypoint_cmd else 0.0
            )
            mav.mission_item_int_send(
                target_system,
                target_component,
                seq,
                frame,
                command,
                1 if seq == 0 else 0,  # current
                0 if is_last else 1,  # stop on the last item
                0,
                accept_m,
                0,
                0,
                int(lat * 1e7),
                int(lon * 1e7),
                alt,
            )
        ack = conn.recv_match(type="MISSION_ACK", blocking=True, timeout=5.0)
        if ack is None:
            raise TimeoutError("No MISSION_ACK")
        if int(getattr(ack, "type", -1)) != 0:
            ack_type = getattr(ack, "type", None)
            raise RuntimeError(f"MISSION_ACK type={ack_type}")
        first, last = waypoints[0], waypoints[-1]
        LOGGER.info(
            "Uploaded PX4 mission: %s + %s waypoints (last_seq=%s) "
            "first=%.5f,%.5f last=%.5f,%.5f alt=%.1fm",
            "takeoff" if include_takeoff else "no-takeoff",
            len(waypoints),
            last_wp_seq,
            first.latitude_deg,
            first.longitude_deg,
            last.latitude_deg,
            last.longitude_deg,
            float(last.altitude_m if last.altitude_m is not None else 50.0),
        )
        return last_wp_seq

    def _arm_locked(self, *, force: bool = False) -> None:
        """Arm motors. Caller must hold ``_io_lock``."""
        # pylint: disable-next=import-outside-toplevel
        from pymavlink import mavutil

        if self._is_armed():
            return
        conn = self._require_conn()
        # param2=21196 forces arm in SITL when prechecks would block.
        force_param = 21196.0 if force else 0.0
        last_error: Exception | None = None
        for _ in range(5):
            conn.mav.command_long_send(
                conn.target_system,
                conn.target_component,
                mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                0,
                1.0,
                force_param,
                0,
                0,
                0,
                0,
                0,
            )
            try:
                self._wait_command_ack_locked(
                    mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
                )
                last_error = None
                break
            except RuntimeError as exc:
                last_error = exc
                if "result=1" not in str(exc):
                    raise
                time.sleep(0.2)
        if last_error is not None:
            raise last_error
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
            if msg is not None:
                self._ingest(msg)
            if self._is_armed():
                LOGGER.info("PX4 armed")
                return
        raise TimeoutError("Timed out waiting for PX4 armed")

    def _wait_airborne_locked(self, alt_m: float) -> None:
        """Wait until relative altitude shows climb. Holds ``_io_lock``."""
        airborne_m = min(5.0, max(2.0, alt_m * 0.25))
        if self._relative_alt_m() >= airborne_m:
            LOGGER.info("PX4 already airborne; skipping climb wait")
            return
        conn = self._require_conn()
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            if self._hsa_live is not None:
                self._send_offboard_setpoint_locked()
            msg = conn.recv_match(blocking=True, timeout=0.1)
            if msg is not None:
                self._ingest(msg)
            if self._relative_alt_m() >= airborne_m:
                LOGGER.info(
                    "PX4 airborne relative_alt=%.1fm (target=%.1fm)",
                    self._relative_alt_m(),
                    alt_m,
                )
                return
        raise TimeoutError(
            "Timed out waiting for takeoff "
            f"(rel_alt={self._relative_alt_m():.1f}m target={alt_m:.1f}m)"
        )

    def _start_mission_locked(self) -> None:
        """Switch to MISSION and start. Caller must hold ``_io_lock``."""
        # pylint: disable-next=import-outside-toplevel
        from pymavlink import mavutil

        conn = self._require_conn()
        if not self._set_mode_locked("MISSION"):
            self._set_mode_locked("AUTO.MISSION")
        conn.mav.command_long_send(
            conn.target_system,
            conn.target_component,
            mavutil.mavlink.MAV_CMD_MISSION_START,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        )
        try:
            self._wait_command_ack_locked(
                mavutil.mavlink.MAV_CMD_MISSION_START, timeout=5.0
            )
        except TimeoutError:
            LOGGER.warning("No ACK for MISSION_START; continuing")
        LOGGER.info("PX4 mission started")

    def _set_mode_locked(self, name: str) -> bool:
        """Set a PX4 mode by name. Caller must hold ``_io_lock``."""
        conn = self._require_conn()
        mapping = conn.mode_mapping() or {}
        mode = mapping.get(name)
        if mode is None:
            return False
        try:
            if isinstance(mode, tuple) and len(mode) == 3:
                conn.set_mode(mode[0], mode[1], mode[2])
            else:
                conn.set_mode(mode)
        except Exception:  # pylint: disable=broad-exception-caught
            LOGGER.warning("set_mode(%s) failed", name, exc_info=True)
            return False
        return True

    def _wait_command_ack_locked(
        self, command: int, timeout: float = 5.0
    ) -> None:
        """Block until COMMAND_ACK for *command*. Caller holds ``_io_lock``."""
        conn = self._require_conn()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = conn.recv_match(
                type="COMMAND_ACK", blocking=True, timeout=1.0
            )
            if msg is None:
                continue
            if int(getattr(msg, "command", -1)) != int(command):
                continue
            result = int(getattr(msg, "result", -1))
            # MAV_RESULT_ACCEPTED = 0, IN_PROGRESS = 5
            if result in (0, 5):
                return
            raise RuntimeError(f"COMMAND_ACK command={command} result={result}")
        raise TimeoutError(f"No COMMAND_ACK for command={command}")

    def _require_conn(self) -> Any:
        """Return the open MAVLink connection, or raise if closed."""
        if self._conn is None:
            raise RuntimeError("PX4 not connected")
        return self._conn

    def _is_armed(self) -> bool:
        """Last HEARTBEAT safety-armed flag."""
        with self._lock:
            return self._cache.armed

    def _relative_alt_m(self) -> float:
        """AGL from ``GLOBAL_POSITION_INT.relative_alt``."""
        with self._lock:
            return self._cache.relative_alt_m
