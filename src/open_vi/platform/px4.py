"""PX4 / SITL backend via MAVLink (pymavlink)."""

from __future__ import annotations

import hashlib
import logging
import math
import os
import threading
import time
from dataclasses import dataclass, replace
from typing import Any
from uuid import UUID, uuid4

from open_vi.platform.port import (
    CommandResult,
    ControlOffer,
    ControlReadiness,
    FaultSnapshot,
    FlightActivitySnapshot,
    FlightCommandRequest,
    PlatformPort,
    PlatformSnapshot,
    RouteActivationRequest,
    RouteActivationResult,
    ServiceStatusSnapshot,
    StoredRoutePlan,
    SubsystemStatusSnapshot,
    TsipSnapshot,
    Waypoint,
)

LOGGER = logging.getLogger(__name__)


_EARTH_M = 6_378_137.0
# Must match open_ma OmplPathPlanner._PATH_CLEARANCE_M.
_PATH_CLEARANCE_M = 15.0


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
    capture_m: float = _PATH_CLEARANCE_M,
) -> tuple[Waypoint, ...]:
    """Drop prefix WPs already captured or behind the vehicle toward the goal.

    A mid-flight replan often starts with the current pose, then an RRT
    vertex behind the aircraft. Uploading that prefix makes PX4 turn
    around. Keep the goal.
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
_ACCEPTED_MODES = frozenset({"WAYPOINT_FOLLOWING"})

# Same route SM as Stub for Isolator sequences; vehicle push is later.
_ROUTE_TRANSITIONS: dict[
    str, tuple[frozenset[str | None], str | None, str, bool]
] = {
    "PREPARE_FOR_UPLOAD": (
        frozenset({None, "INACTIVE", "DEACTIVATED", "READY_FOR_UPLOAD"}),
        "PREPARING_FOR_UPLOAD",
        "READY_FOR_UPLOAD",
        True,
    ),
    "UPLOAD": (
        frozenset({"READY_FOR_UPLOAD"}),
        "UPLOADING",
        "UPLOADED",
        True,
    ),
    "PREPARE_FOR_ACTIVATION": (
        frozenset({"UPLOADED"}),
        "PREPARING_FOR_ACTIVATION",
        "READY_FOR_ACTIVATION",
        True,
    ),
    "ACTIVATE": (
        frozenset({"READY_FOR_ACTIVATION"}),
        "ACTIVATING",
        "ACTIVATED",
        True,
    ),
    "DEACTIVATE": (
        frozenset({"READY_FOR_ACTIVATION", "ACTIVATED"}),
        None,
        "DEACTIVATED",
        False,
    ),
}


@dataclass
class _RouteRecord:
    route_plan_id: UUID
    mission_plan_id: UUID | None = None
    state: str = "INACTIVE"
    xml: str | None = None
    sha256_hex: str | None = None


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
    battery_remaining: int | None = None
    system_status: int = 0
    armed: bool = False
    base_mode: int = 0


class Px4MavlinkAdapter(PlatformPort):
    """PX4 adapter: telemetry + waypoint mission execute (arm/takeoff/start).

    Connects with pymavlink (default ``udpin:127.0.0.1:14540`` for SITL).
    Install: ``pip install -e ".[px4]"``.
    Arm/takeoff/mission-start are adapter-internal — not separate VI ICD steps.
    """

    def __init__(
        self,
        connection_url: str | None = None,
        *,
        autoconnect: bool = True,
        heartbeat_timeout_s: float | None = None,
        connection: Any | None = None,
        takeoff_alt_m: float = 30.0,
    ) -> None:
        self.connection_url = connection_url or os.environ.get(
            "PX4_MAVLINK_URL", DEFAULT_MAVLINK_URL
        )
        self._heartbeat_timeout_s = (
            heartbeat_timeout_s
            if heartbeat_timeout_s is not None
            else float(os.environ.get("PX4_HEARTBEAT_TIMEOUT_S", "10"))
        )
        self._takeoff_alt_m = takeoff_alt_m
        self._conn: Any | None = connection
        self._offer = ControlOffer(
            capability_types=("WAYPOINT_FOLLOWING",),
            capability_label="px4-flight-capability",
        )
        self._activity: FlightActivitySnapshot | None = None
        self._commands: dict[UUID, str] = {}
        self._pending_updates: list[tuple[UUID, CommandResult]] = []
        self._active_command_id: UUID | None = None
        self._mission_last_seq: int | None = None
        self._routes: dict[UUID, _RouteRecord] = {}
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
        self._kollsman_hpa = 1013.25
        if autoconnect and self._conn is None:
            self.connect()

    def connect(self) -> None:
        """Open MAVLink and start the telemetry reader."""
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
        return PlatformSnapshot(offer=self._offer, readiness=readiness)

    def submit_flight_command(self, cmd: FlightCommandRequest) -> CommandResult:
        snap = self.snapshot()
        if not snap.readiness.available:
            return CommandResult(
                processing_state="REJECTED",
                reason="CAPABILITY_UNAVAILABLE",
                reason_description="PX4 link not available",
            )
        if cmd.choice != "Capability":
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description="Activity modify not supported yet",
            )
        if cmd.command_state == "CANCEL":
            if cmd.command_id in self._commands:
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
        if cmd.mode not in _ACCEPTED_MODES:
            return CommandResult(
                processing_state="REJECTED",
                reason="CAPABILITY_UNAVAILABLE",
                reason_description=(
                    "PX4 adapter v0 accepts WAYPOINT_FOLLOWING only; "
                    f"got {cmd.mode}"
                ),
            )
        if not cmd.waypoints:
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description="WAYPOINT_FOLLOWING requires waypoints",
            )
        try:
            self._execute_waypoint_following(cmd.waypoints)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            LOGGER.exception("PX4 waypoint execution failed")
            return CommandResult(
                processing_state="REJECTED",
                reason="FAILED",
                reason_description=f"Waypoint execution failed: {exc}",
            )
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

    def poll_command_updates(self) -> list[tuple[UUID, CommandResult]]:
        with self._lock:
            updates = list(self._pending_updates)
            self._pending_updates.clear()
            return updates

    def active_flight_activity(self) -> FlightActivitySnapshot | None:
        return self._activity

    def get_vehicle_state(self) -> TsipSnapshot:
        with self._lock:
            c = self._cache
            fuel = 85.0
            if c.battery_remaining is not None:
                fuel = float(c.battery_remaining)
            heading_rad = math.radians(c.heading_deg)
            return TsipSnapshot(
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
                magnetic_heading_rad=heading_rad,
                component_id=self._component_id,
                component_label="px4",
                component_state="OPERATIONAL",
            )

    def get_service_status(self) -> ServiceStatusSnapshot:
        secs = max(0, int(time.monotonic() - self._started))
        return ServiceStatusSnapshot(
            service_id=self._service_id,
            service_label="open-vi-px4",
            time_up=f"PT{secs}S",
        )

    def get_subsystem_status(self) -> SubsystemStatusSnapshot:
        return SubsystemStatusSnapshot(
            subsystem_id=self._subsystem_id,
            subsystem_label="flight",
            subsystem_state="OPERATE",
            model="px4",
            software_version="sitl",
        )

    def get_faults(self) -> tuple[FaultSnapshot, ...]:
        return (FaultSnapshot(fault_id=self._fault_id),)

    def apply_system_management(self, *, qnh_kpa: float | None = None) -> str:
        if qnh_kpa is None:
            return "COMPLETED"
        self._kollsman_hpa = float(qnh_kpa) * 10.0
        return "COMPLETED"

    def handle_route_activation(
        self, req: RouteActivationRequest
    ) -> RouteActivationResult:
        transition = _ROUTE_TRANSITIONS.get(req.command_type)
        if transition is None:
            return RouteActivationResult(
                processing_state="REJECTED",
                plan_state="INACTIVE",
                emit_pair=False,
                reason="INVALID_INPUT_PARAMETER",
                reason_description=(
                    f"Unsupported CommandType {req.command_type}"
                ),
            )
        allowed, mid, terminal, emit_pair = transition
        record = self._routes.get(req.route_plan_id)
        current = record.state if record is not None else None
        if current not in allowed:
            return RouteActivationResult(
                processing_state="REJECTED",
                plan_state=current or "INACTIVE",
                emit_pair=False,
                reason="INVALID_INPUT_PARAMETER",
                reason_description=(
                    f"Cannot {req.command_type} from state {current}"
                ),
            )
        if req.command_type == "UPLOAD" and (
            record is None or record.xml is None
        ):
            return RouteActivationResult(
                processing_state="REJECTED",
                plan_state=current or "INACTIVE",
                emit_pair=False,
                reason="INVALID_INPUT_PARAMETER",
                reason_description="No stored MA_RoutePlan for UPLOAD",
            )
        if record is None:
            record = _RouteRecord(
                route_plan_id=req.route_plan_id,
                mission_plan_id=req.mission_plan_id,
            )
            self._routes[req.route_plan_id] = record
        record.mission_plan_id = req.mission_plan_id
        record.state = terminal
        return RouteActivationResult(
            processing_state="ACCEPTED",
            plan_state=terminal,
            progress_state=mid,
            emit_pair=emit_pair,
        )

    def store_route_plan(
        self,
        route_plan_id: UUID,
        xml: str,
        *,
        mission_plan_id: UUID | None = None,
    ) -> StoredRoutePlan:
        digest = hashlib.sha256(xml.encode("utf-8")).hexdigest()
        record = self._routes.get(route_plan_id)
        if record is None:
            record = _RouteRecord(route_plan_id=route_plan_id)
            self._routes[route_plan_id] = record
        if mission_plan_id is not None:
            record.mission_plan_id = mission_plan_id
        record.xml = xml
        record.sha256_hex = digest
        if record.state in (None, "INACTIVE", "DEACTIVATED"):
            record.state = "READY_FOR_UPLOAD"
        return StoredRoutePlan(
            route_plan_id=route_plan_id,
            xml=xml,
            sha256_hex=digest,
            mission_plan_id=record.mission_plan_id,
            plan_state=record.state,
        )

    def get_stored_route(self, route_plan_id: UUID) -> StoredRoutePlan | None:
        record = self._routes.get(route_plan_id)
        if record is None or record.xml is None or record.sha256_hex is None:
            return None
        return StoredRoutePlan(
            route_plan_id=record.route_plan_id,
            xml=record.xml,
            sha256_hex=record.sha256_hex,
            mission_plan_id=record.mission_plan_id,
            plan_state=record.state,
        )

    def _link_ok(self) -> bool:
        if self._conn is None:
            return False
        with self._lock:
            last = self._cache.last_heartbeat_mono
        if last <= 0.0:
            return False
        return (time.monotonic() - last) <= _HEARTBEAT_STALE_S

    def _reader_loop(self) -> None:
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
                self._cache.heading_deg = float(msg.hdg) / 100.0
            elif mtype == "ATTITUDE":
                self._cache.last_heartbeat_mono = time.monotonic()
                self._cache.roll_rad = float(msg.roll)
                self._cache.pitch_rad = float(msg.pitch)
                self._cache.yaw_rad = float(msg.yaw)
            elif mtype == "VFR_HUD":
                airspeed = float(msg.airspeed)
                groundspeed = float(msg.groundspeed)
                self._cache.airspeed_mps = (
                    airspeed if math.isfinite(airspeed) else 0.0
                )
                self._cache.groundspeed_mps = (
                    groundspeed if math.isfinite(groundspeed) else 0.0
                )
                self._cache.heading_deg = float(msg.heading)
            elif mtype == "SYS_STATUS":
                rem = int(getattr(msg, "battery_remaining", -1))
                self._cache.battery_remaining = rem if rem >= 0 else None
            elif mtype == "MISSION_ITEM_REACHED":
                seq = int(getattr(msg, "seq", -1))
                self._maybe_complete_mission_locked(seq)

    def _maybe_complete_mission_locked(self, seq: int) -> None:
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
        """Home HAE from GLOBAL_POSITION_INT: AMSL minus relative-to-home."""
        with self._lock:
            alt = self._cache.alt_m
            rel = self._cache.relative_alt_m
        if alt == 0.0 and rel == 0.0:
            return None
        return alt - rel

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

        C2 cruise is first-pose HAE + 50 m (`CRUISE_AGL_M` in the C2
        client). This still flattens every item to current AGL so SIH
        3D capture can succeed if a later command arrives at a different HAE.
        """
        rel = self._relative_alt_m()
        if rel >= 2.0:
            return rel
        return self._takeoff_alt_m

    def _apply_nav_params(self) -> None:
        """Set MC acceptance to the planner disk so edge-hug WPs are flown."""
        # pylint: disable-next=import-outside-toplevel
        from pymavlink import mavutil

        conn = self._conn
        if conn is None or not hasattr(conn.mav, "param_set_send"):
            return
        for name, value in (
            ("NAV_ACC_RAD", _PATH_CLEARANCE_M),
            ("NAV_MC_ALT_RAD", _PATH_CLEARANCE_M),
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
            _PATH_CLEARANCE_M,
            _PATH_CLEARANCE_M,
        )

    def _execute_waypoint_following(
        self, waypoints: tuple[Waypoint, ...]
    ) -> None:
        """Upload mission, arm, start MISSION mode.

        A replacement while airborne must not restart NAV_TAKEOFF at the
        planner start — that is how a mid-mission replan (zone arrives
        after the first command) leaves SIH holding at an intermediate
        vertex. Drop waypoints already under the vehicle and start at the
        next remaining item.
        """
        remaining = self._remaining_waypoints(waypoints)
        if len(remaining) < len(waypoints):
            LOGGER.info(
                "PX4 skipped %d prefix WPs (kept %d, capture=%.0fm)",
                len(waypoints) - len(remaining),
                len(remaining),
                _PATH_CLEARANCE_M,
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
        return advance_mission_waypoints(waypoints, here)

    def _current_ll(self) -> tuple[float, float] | None:
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
        # Standalone NAV_TAKEOFF / TAKEOFF mode sits at MIS_TAKEOFF_ALT on
        # SIH; embedding takeoff as mission item 0 then MISSION_START works.
        # Skip takeoff when already airborne — a replan must not restart it.
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
            accept_m = _PATH_CLEARANCE_M if command == waypoint_cmd else 0.0
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
        self._wait_command_ack_locked(
            mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM
        )
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
            msg = conn.recv_match(blocking=True, timeout=1.0)
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
        if self._conn is None:
            raise RuntimeError("PX4 not connected")
        return self._conn

    def _is_armed(self) -> bool:
        with self._lock:
            return self._cache.armed

    def _relative_alt_m(self) -> float:
        with self._lock:
            return self._cache.relative_alt_m
