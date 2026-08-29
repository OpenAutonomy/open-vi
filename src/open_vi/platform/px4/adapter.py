"""PX4 / SITL :class:`PlatformPort` composed from link, mission, offboard.

Telemetry, ``WAYPOINT_FOLLOWING``, ``CURVE_FOLLOWING`` (sampled
NURBS as a mission), and ``HSA_CSA`` (offboard hold). Isolator and
the codec never import this module or MAVLink types —
``make_platform("px4")`` loads it. A second vehicle reuses the
sibling modules; it does not copy this class.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections.abc import Callable
from dataclasses import replace
from typing import Any
from uuid import UUID, uuid4

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
from open_vi.platform.px4.link import (
    DEFAULT_MAVLINK_URL,
    CommandCanceled,
    MavlinkLink,
)
from open_vi.platform.px4.mission import (
    DEFAULT_PATH_CLEARANCE_M,
    execute_waypoint_following,
    mission_rel_alt_m,
)
from open_vi.platform.px4.offboard import OffboardHold, resolve_hsa
from open_vi.platform.px4.telemetry import (
    MavCache,
    freeze_home_hae,
    ingest,
    link_down_fault,
    link_fresh,
    sensor_faults,
    tspi_from_cache,
)
from open_vi.platform.px4_config import (
    Px4VehicleConfig,
    load_px4_vehicle_config,
)

LOGGER = logging.getLogger(__name__)

DEFAULT_MIN_REL_ALT_M = 10.0
DEFAULT_MAX_REL_ALT_M = 500.0


def _load_vehicle(
    config: Px4VehicleConfig | None, config_path: str | None
) -> Px4VehicleConfig:
    """Constructor object, then path / ``PX4_CONFIG``, else empty."""
    if config is not None:
        return config
    path = config_path or os.environ.get("PX4_CONFIG") or ""
    if path.strip():
        return load_px4_vehicle_config(path)
    return Px4VehicleConfig()


def _first_present(*values: object) -> float:
    """First non-None value as float (env strings included)."""
    for value in values:
        if value is not None:
            return float(value)
    raise ValueError("expected a fallback value")


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
        config: Px4VehicleConfig | None = None,
        config_path: str | None = None,
    ) -> None:
        url = connection_url or os.environ.get(
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
        self._vehicle = _load_vehicle(config, config_path)
        self._min_rel_alt_m = _first_present(
            min_rel_alt_m,
            self._vehicle.min_rel_alt_m,
            os.environ.get("PX4_MIN_REL_ALT_M"),
            DEFAULT_MIN_REL_ALT_M,
        )
        self._max_rel_alt_m = _first_present(
            max_rel_alt_m,
            self._vehicle.max_rel_alt_m,
            os.environ.get("PX4_MAX_REL_ALT_M"),
            DEFAULT_MAX_REL_ALT_M,
        )
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
        self._exec_thread: threading.Thread | None = None
        self._exec_cancel = threading.Event()
        self._service_id = uuid4()
        self._subsystem_id = uuid4()
        self._fault_id = uuid4()
        self._component_id = uuid4()
        self._started = time.monotonic()
        self._cache = MavCache()
        self._lock = threading.Lock()
        self._home_hae_frozen: float | None = None
        self._kollsman_hpa = 1013.25
        self._link = MavlinkLink(
            url,
            heartbeat_timeout_s=self._heartbeat_timeout_s,
            on_message=self._ingest,
            connection=connection,
        )
        self._offboard = OffboardHold(self._link, self._lock)
        if autoconnect and self._link.conn is None:
            self.connect()

    @property
    def connection_url(self) -> str:
        """MAVLink URL passed to pymavlink."""
        return self._link.connection_url

    @property
    def _conn(self) -> Any | None:
        """Open MAVLink connection (tests and helpers)."""
        return self._link.conn

    @_conn.setter
    def _conn(self, value: Any | None) -> None:
        self._link.conn = value

    @property
    def _hsa_live(self) -> Any:
        """Resolved offboard vector, or ``None``."""
        return self._offboard.live

    @property
    def _offboard_thread(self) -> threading.Thread | None:
        """Offboard writer thread, or ``None``."""
        return self._offboard.thread

    def connect(self) -> None:
        """Open MAVLink, wait for HEARTBEAT, apply nav params, start reader."""
        if self._link.conn is not None:
            return
        self._link.connect()
        with self._lock:
            self._cache.last_heartbeat_mono = time.monotonic()
        self._link.apply_nav_params(self._path_clearance_m)
        self._link.start_reader()

    def close(self) -> None:
        """Stop execution, reader, and offboard threads; close MAVLink."""
        self._cancel_and_join_exec()
        self._offboard.stop()
        self._link.close()

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
        extras = self._vehicle.profile
        home = self._home_hae_m()
        if home is None:
            return replace(
                extras,
                min_altitude_m=min_rel_m,
                max_altitude_m=self._max_rel_alt_m,
                altitude_ref="AGL",
            )
        return replace(
            extras,
            min_altitude_m=home + min_rel_m,
            max_altitude_m=home + self._max_rel_alt_m,
            altitude_ref="WGS_HAE",
        )

    def submit_flight_command(self, cmd: FlightCommandRequest) -> CommandResult:
        """Accept waypoint, curve, or HSA NEW when idle, UPDATE, or CANCEL.

        Validation runs synchronously; an accepted command's mission
        I/O (arm, upload, wait for climb) runs on a background thread
        so this call returns promptly (see :meth:`_begin_execution`).
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
                self._cancel_and_join_exec()
                self._offboard.stop()
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
        rejected, runner = self._execute_or_reject(cmd)
        if rejected is not None:
            return rejected
        assert runner is not None
        return self._begin_execution(
            cmd, activity_id=uuid4(), new_activity=True, runner=runner
        )

    def _submit_activity(self, cmd: FlightCommandRequest) -> CommandResult:
        """Replace the live path; keep ``activity_id``."""
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
        rejected, runner = self._execute_or_reject(cmd)
        if rejected is not None:
            return rejected
        assert runner is not None
        return self._begin_execution(
            cmd, activity_id=live.activity_id, new_activity=False, runner=runner
        )

    def _wait_exec_idle(self, timeout: float = 2.0) -> None:
        """Block until the current background execution finishes.

        Test-only synchronization point: production code never needs to
        wait on the exec thread, since its outcome is reported async via
        ``poll_command_updates``.
        """
        thread = self._exec_thread
        if thread is not None:
            thread.join(timeout=timeout)

    def _cancel_and_join_exec(self, timeout: float = 2.0) -> None:
        """Cancel and wait for any in-flight background execution.

        Called before CANCEL cleanup (so a stuck ``wait_airborne``
        doesn't keep ``link.io_lock`` while we try to hold/disarm) and
        before starting a new execution (so a replan doesn't race the
        previous one). Gives up and logs after *timeout* rather than
        blocking forever.
        """
        self._exec_cancel.set()
        thread = self._exec_thread
        if thread is not None and thread.is_alive():
            thread.join(timeout=timeout)
            if thread.is_alive():
                LOGGER.warning(
                    "PX4 execution thread did not stop within %.1fs", timeout
                )

    def _begin_execution(
        self,
        cmd: FlightCommandRequest,
        *,
        activity_id: UUID,
        new_activity: bool,
        runner: Callable[[], None],
    ) -> CommandResult:
        """Accept *cmd*, then run *runner* (mission I/O) off this thread."""
        self._cancel_and_join_exec()
        with self._lock:
            if new_activity:
                self._activity = FlightActivitySnapshot(
                    activity_id=activity_id,
                    capability_id=cmd.capability_id,
                    activity_state="ACTIVE_UNCONSTRAINED",
                    interactive=True,
                )
            self._commands[cmd.command_id] = "ACCEPTED"
            self._active_command_id = cmd.command_id
        self._exec_cancel = threading.Event()
        self._exec_thread = threading.Thread(
            target=self._run_execution,
            args=(cmd.command_id, activity_id, runner),
            name="open-vi-px4-command",
            daemon=True,
        )
        self._exec_thread.start()
        return CommandResult(
            processing_state="ACCEPTED",
            activity_id=activity_id,
            new_activity=new_activity,
        )

    def _run_execution(
        self,
        command_id: UUID,
        activity_id: UUID,
        runner: Callable[[], None],
    ) -> None:
        """Run *runner* off the calling thread; report a failure async.

        A cancellation is expected (CANCEL already published its own
        status synchronously) and logged only. Any other exception
        reports ``FAILED`` through ``poll_command_updates`` unless
        *command_id* was superseded by a CANCEL or a later command
        first.
        """
        try:
            runner()
        except CommandCanceled:
            LOGGER.info(
                "PX4 command %s canceled during execution", command_id.hex
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            LOGGER.exception("PX4 command execution failed")
            with self._lock:
                if self._commands.get(command_id) != "ACCEPTED":
                    return
                self._commands[command_id] = "FAILED"
                self._activity = None
                if self._active_command_id == command_id:
                    self._active_command_id = None
                    self._mission_last_seq = None
                self._pending_updates.append(
                    (
                        command_id,
                        CommandResult(
                            processing_state="FAILED",
                            reason="STATE_OR_SETTINGS",
                            reason_description=f"PX4 execution failed: {exc}",
                            activity_id=activity_id,
                        ),
                    )
                )

    def _execute_or_reject(
        self, cmd: FlightCommandRequest
    ) -> tuple[CommandResult | None, Callable[[], None] | None]:
        """Validate, or return a runner to fly waypoints, a curve, or HSA."""
        if cmd.mode == "HSA_CSA":
            return self._execute_hsa_or_reject(cmd)
        if cmd.mode == "CURVE_FOLLOWING":
            return self._execute_curve_or_reject(cmd)
        if cmd.mode != "WAYPOINT_FOLLOWING":
            return (
                CommandResult(
                    processing_state="REJECTED",
                    reason="CAPABILITY_UNAVAILABLE",
                    reason_description=(
                        "PX4 adapter accepts WAYPOINT_FOLLOWING, "
                        f"CURVE_FOLLOWING, and HSA_CSA; got {cmd.mode}"
                    ),
                    validation_results=("CAPABILITY_NOT_SUPPORTED",),
                ),
                None,
            )
        rejected = validate_waypoint_path(
            cmd.waypoints,
            min_rel_alt_m=self._min_rel_alt_m,
            max_rel_alt_m=self._max_rel_alt_m,
            home_hae_m=self._home_hae_m(),
        )
        if rejected is not None:
            return rejected, None
        self._offboard.stop()
        waypoints = cmd.waypoints
        return None, lambda: self._execute_waypoint_following(
            waypoints, cancel=self._exec_cancel
        )

    def _execute_curve_or_reject(
        self, cmd: FlightCommandRequest
    ) -> tuple[CommandResult | None, Callable[[], None] | None]:
        """Sample the NURBS to waypoints and return a runner to fly it."""
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
            return rejected, None
        if curve is None:
            return (
                CommandResult(
                    processing_state="REJECTED",
                    reason="INVALID_INPUT_PARAMETER",
                    reason_description="CURVE_FOLLOWING requires CurveSegments",
                    validation_results=("INVALID_WAYPOINT",),
                ),
                None,
            )
        waypoints = sample_curve_waypoints(curve, altitude_m=altitude_m)
        self._offboard.stop()
        return None, lambda: self._execute_waypoint_following(
            waypoints, cancel=self._exec_cancel
        )

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
    ) -> tuple[CommandResult | None, Callable[[], None] | None]:
        """Validate, or return a runner that starts/replaces the hold."""
        rejected = validate_hsa_setpoint(
            cmd.hsa,
            min_rel_alt_m=0.0,
            max_rel_alt_m=self._max_rel_alt_m,
            home_hae_m=self._home_hae_m(),
        )
        if rejected is not None:
            return rejected, None
        hsa = cmd.hsa or HsaCsaSetpoint()
        return None, lambda: self._execute_hsa_csa(
            hsa, cancel=self._exec_cancel
        )

    def _execute_hsa_csa(
        self, hsa: HsaCsaSetpoint, *, cancel: threading.Event | None = None
    ) -> None:
        """Hold or replace an offboard heading/speed/altitude vector."""
        live = self._resolve_hsa(hsa)
        with self._lock:
            self._mission_last_seq = None
        airborne = self._relative_alt_m() >= 2.0
        self._offboard.start_or_replace(
            live,
            airborne=airborne,
            is_armed=self._is_armed,
            ingest=self._ingest,
            wait_ack=self._wait_command_ack_locked,
            relative_alt_m=self._relative_alt_m,
            cancel=cancel,
        )

    def _resolve_hsa(self, hsa: HsaCsaSetpoint) -> Any:
        """Fill omitted axes from telemetry and leftover-ref conversions."""
        with self._lock:
            home = freeze_home_hae(self._cache, self._home_hae_frozen)
            if home is not None and self._home_hae_frozen is None:
                self._home_hae_frozen = home
            return resolve_hsa(
                hsa,
                self._cache,
                home_hae_m=self._home_hae_frozen,
                takeoff_alt_m=self._takeoff_alt_m,
            )

    def _hold_if_linked(self) -> None:
        """LOITER/HOLD when a link exists. Best-effort."""
        if self._link.conn is None:
            return
        with self._link.io_lock:
            self._link.hold()

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
            return tspi_from_cache(
                self._cache,
                kollsman_hpa=self._kollsman_hpa,
                component_id=self._component_id,
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
            return (link_down_fault(),)
        with self._lock:
            faults = sensor_faults(self._cache)
        if faults:
            return faults
        return (FaultSnapshot(fault_id=self._fault_id),)

    def _bit_failed(self) -> bool:
        """True when the link is down or a watched sensor is unhealthy."""
        if not self._link_ok():
            return True
        with self._lock:
            return bool(sensor_faults(self._cache))

    def apply_system_management(self, *, qnh_kpa: float | None = None) -> str:
        """Write QNH to PX4 and the local TSPI snapshot."""
        if qnh_kpa is None:
            return "COMPLETED"
        hpa = float(qnh_kpa) * 10.0
        if not self._link_ok():
            return "REJECTED"
        try:
            self._link.set_qnh_hpa(hpa)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            LOGGER.warning("PX4 QNH PARAM_SET failed: %s", exc)
            return "REJECTED"
        self._kollsman_hpa = hpa
        return "COMPLETED"

    def _link_ok(self) -> bool:
        """True when a HEARTBEAT or position update is newer than 10 s."""
        with self._lock:
            return link_fresh(
                self._cache, connected=self._link.conn is not None
            )

    def _ingest(self, msg: Any) -> None:
        """Update the telemetry cache; complete the mission if reached."""
        with self._lock:
            seq = ingest(self._cache, msg)
            if seq is not None:
                self._maybe_complete_mission_locked(seq)

    def _maybe_complete_mission_locked(self, seq: int) -> None:
        """Queue ``COMPLETED`` when *seq* reaches the last uploaded waypoint."""
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
        """Home HAE from GLOBAL_POSITION_INT; first fix is frozen."""
        with self._lock:
            home = freeze_home_hae(self._cache, self._home_hae_frozen)
            if home is not None and self._home_hae_frozen is None:
                self._home_hae_frozen = home
            return self._home_hae_frozen

    def _mission_rel_alt_m(self, altitude_m: float | None) -> float:
        """A-GRA Point2D altitude is HAE; PX4 items are relative to home."""
        return mission_rel_alt_m(
            altitude_m,
            home_hae_m=self._home_hae_m(),
            takeoff_alt_m=self._takeoff_alt_m,
        )

    def _execute_waypoint_following(
        self,
        waypoints: tuple[Waypoint, ...],
        *,
        cancel: threading.Event | None = None,
    ) -> None:
        """Upload mission, arm, start MISSION mode."""
        last_seq = execute_waypoint_following(
            self._link,
            waypoints,
            here=self._current_ll(),
            relative_alt_m=self._relative_alt_m,
            takeoff_alt_m=self._takeoff_alt_m,
            path_clearance_m=self._path_clearance_m,
            is_armed=self._is_armed,
            ingest=self._ingest,
            wait_ack=self._wait_command_ack_locked,
            cancel=cancel,
        )
        with self._lock:
            self._mission_last_seq = last_seq

    def _current_ll(self) -> tuple[float, float] | None:
        """Cached lat/lon, or ``None`` before the first position."""
        with self._lock:
            lat = self._cache.lat_deg
            lon = self._cache.lon_deg
        if lat == 0.0 and lon == 0.0:
            return None
        return lat, lon

    def _wait_command_ack_locked(
        self, command: int, timeout: float = 5.0
    ) -> None:
        """Block until COMMAND_ACK. Tests may replace this method."""
        self._link.wait_command_ack(command, timeout)

    def _is_armed(self) -> bool:
        """Last HEARTBEAT safety-armed flag."""
        with self._lock:
            return self._cache.armed

    def _relative_alt_m(self) -> float:
        """AGL from ``GLOBAL_POSITION_INT.relative_alt``."""
        with self._lock:
            return self._cache.relative_alt_m
