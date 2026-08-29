"""PX4 HSA/CSA offboard hold: ISA convert, setpoint stream.

A second adapter can reuse :func:`resolve_hsa` and :class:`OffboardHold`
without the mission-upload path.
"""

from __future__ import annotations

import logging
import math
import threading
from collections.abc import Callable
from dataclasses import dataclass

from open_vi.domain import HsaCsaSetpoint
from open_vi.platform.px4.link import MavlinkLink
from open_vi.platform.px4.telemetry import MavCache, wind_ned

LOGGER = logging.getLogger(__name__)

_ISA_T0_K = 288.15
_ISA_L_K_PER_M = 0.0065
_ISA_P0_PA = 101325.0
_ISA_G = 9.80665
_ISA_R = 287.05
_ISA_GAMMA = 1.4
_ISA_RHO0 = 1.225
_TROPO_MAX_M = 11000.0
_OFFBOARD_HZ = 10.0
_OFFBOARD_PRIME = 5


@dataclass
class ResolvedHsa:
    """Live offboard vector (NED yaw / groundspeed / AGL)."""

    heading_deg: float
    speed_mps: float
    rel_alt_m: float


def isa_temperature_k(alt_m: float) -> float:
    """ISA troposphere temperature (K) from AMSL metres."""
    height = min(max(alt_m, 0.0), _TROPO_MAX_M)
    return _ISA_T0_K - _ISA_L_K_PER_M * height


def isa_pressure_pa(alt_m: float) -> float:
    """ISA troposphere static pressure (Pa) from AMSL metres."""
    temp_k = isa_temperature_k(alt_m)
    exponent = _ISA_G / (_ISA_L_K_PER_M * _ISA_R)
    return _ISA_P0_PA * (temp_k / _ISA_T0_K) ** exponent


def cas_to_tas_mps(
    cas_mps: float, *, pressure_pa: float, temp_k: float
) -> float:
    """Calibrated airspeed to TAS using density ratio."""
    rho = pressure_pa / (_ISA_R * temp_k)
    sigma = rho / _ISA_RHO0
    if sigma <= 0.0:
        return cas_mps
    return cas_mps / math.sqrt(sigma)


def mach_to_tas_mps(mach: float, temp_k: float) -> float:
    """Mach to TAS at static temperature *temp_k*."""
    return mach * math.sqrt(_ISA_GAMMA * _ISA_R * temp_k)


def tas_to_gs_mps(
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


def wrap_heading_deg(heading_deg: float) -> float:
    """Wrap degrees into ``[0, 360)``."""
    return heading_deg % 360.0


def true_heading_deg(
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
    if heading_ref != "MAGNETIC_NORTH":
        return wrap_heading_deg(heading_deg)
    if compass is None or ekf_yaw is None:
        raise RuntimeError(
            "HSA magnetic heading needs EKF yaw and compass heading"
        )
    declination = ekf_yaw - compass
    return wrap_heading_deg(heading_deg + declination)


def hsa_groundspeed_mps(
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
    if hsa.mach is not None:
        tas = mach_to_tas_mps(hsa.mach, temp_k or isa_temperature_k(alt_amsl))
    elif hsa.speed_ref == "CALIBRATED_AIRSPEED":
        tas = cas_to_tas_mps(
            float(hsa.speed_mps or 0.0),
            pressure_pa=pressure_pa or isa_pressure_pa(alt_amsl),
            temp_k=temp_k or isa_temperature_k(alt_amsl),
        )
    elif hsa.speed_ref == "TRUE_AIRSPEED":
        tas = float(hsa.speed_mps or 0.0)
    else:
        return float(hsa.speed_mps or 0.0)
    north, east = wind_ned(
        wind_north=wind_north,
        wind_east=wind_east,
        airspeed=airspeed,
        vx_mps=vx_mps,
        vy_mps=vy_mps,
    )
    return tas_to_gs_mps(tas, heading_deg, north, east)


def resolve_hsa(
    hsa: HsaCsaSetpoint,
    cache: MavCache,
    *,
    home_hae_m: float | None,
    takeoff_alt_m: float,
) -> ResolvedHsa:
    """Fill omitted axes from telemetry and leftover-ref conversions."""
    heading = cache.heading_deg
    speed = cache.groundspeed_mps
    rel = cache.relative_alt_m
    if hsa.heading_deg is not None:
        heading = true_heading_deg(
            hsa.heading_deg,
            hsa.heading_ref,
            compass=cache.compass_heading_deg,
            ekf_yaw=cache.ekf_yaw_deg,
        )
    if hsa.mach is not None or hsa.speed_mps is not None:
        speed = hsa_groundspeed_mps(
            hsa,
            heading_deg=heading,
            wind_north=cache.wind_north_mps,
            wind_east=cache.wind_east_mps,
            airspeed=cache.airspeed_mps,
            vx_mps=cache.vx_mps,
            vy_mps=cache.vy_mps,
            alt_amsl=cache.alt_m,
            temp_k=cache.temperature_k,
            pressure_pa=cache.static_pressure_pa,
        )
    if hsa.altitude_m is not None:
        if hsa.altitude_ref in {"WGS_HAE", "MSL", "ALTITUDE_BAROMETRIC"}:
            if home_hae_m is not None:
                rel = float(hsa.altitude_m) - home_hae_m
            else:
                rel = float(hsa.altitude_m)
        else:
            rel = float(hsa.altitude_m)
    if rel < 2.0:
        rel = takeoff_alt_m
    return ResolvedHsa(
        heading_deg=heading,
        speed_mps=speed,
        rel_alt_m=rel,
    )


class OffboardHold:
    """Stream LOCAL_NED setpoints until stop."""

    def __init__(self, link: MavlinkLink, lock: threading.Lock) -> None:
        self._link = link
        self._lock = lock
        self.live: ResolvedHsa | None = None
        self._stop = threading.Event()
        self.thread: threading.Thread | None = None

    def start_or_replace(
        self,
        live: ResolvedHsa,
        *,
        airborne: bool,
        is_armed: Callable[[], bool],
        ingest: Callable[[object], None],
        wait_ack: Callable[[int, float], None],
        relative_alt_m: Callable[[], float],
    ) -> None:
        """Hold or replace an offboard heading/speed/altitude vector."""
        already = self.thread is not None and self.thread.is_alive()
        with self._lock:
            self.live = live
        if already:
            LOGGER.info(
                "PX4 HSA_CSA setpoint updated hdg=%.1f spd=%.1f alt=%.1f",
                live.heading_deg,
                live.speed_mps,
                live.rel_alt_m,
            )
            return
        try:
            with self._link.io_lock:
                if airborne:
                    self._link.hold()
                self.prime_locked()
                if not self._link.set_mode("OFFBOARD"):
                    raise RuntimeError("PX4 OFFBOARD mode not available")
                self._link.arm(
                    force=True,
                    is_armed=is_armed,
                    ingest=ingest,
                    wait_ack=wait_ack,
                )
                if not airborne:
                    self._link.wait_airborne(
                        live.rel_alt_m,
                        relative_alt_m=relative_alt_m,
                        ingest=ingest,
                        tick=self.send_setpoint_locked,
                    )
            self._start_thread()
        except Exception:
            self.stop()
            raise
        LOGGER.info(
            "PX4 HSA_CSA offboard hdg=%.1f spd=%.1f alt=%.1f",
            live.heading_deg,
            live.speed_mps,
            live.rel_alt_m,
        )

    def stop(self) -> None:
        """Join the offboard writer and clear the live vector."""
        self._stop.set()
        thread = self.thread
        if thread is not None:
            thread.join(timeout=2.0)
            self.thread = None
        with self._lock:
            self.live = None

    def _start_thread(self) -> None:
        """Stream setpoints at ``_OFFBOARD_HZ`` until stop."""
        self._stop.clear()
        self.thread = threading.Thread(
            target=self._loop,
            name="open-vi-px4-offboard",
            daemon=True,
        )
        self.thread.start()

    def _loop(self) -> None:
        """Send LOCAL_NED setpoints until ``_stop``."""
        period = 1.0 / _OFFBOARD_HZ
        while not self._stop.wait(period):
            try:
                with self._link.io_lock:
                    self.send_setpoint_locked()
            except Exception:  # pylint: disable=broad-exception-caught
                LOGGER.exception("PX4 offboard setpoint failed")
                return

    def prime_locked(self) -> None:
        """Send a few setpoints before switching OFFBOARD."""
        for _ in range(_OFFBOARD_PRIME):
            self.send_setpoint_locked()

    def send_setpoint_locked(self) -> None:
        """One SET_POSITION_TARGET_LOCAL_NED. Holds ``io_lock``."""
        # pylint: disable-next=import-outside-toplevel
        from pymavlink import mavutil

        with self._lock:
            live = self.live
        if live is None:
            return
        conn = self._link.require_conn()
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
