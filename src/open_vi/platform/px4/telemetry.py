"""PX4 telemetry cache: ingest MAVLink, BIT, TSPI, home HAE.

A second adapter can reuse :class:`MavCache` and :func:`ingest` without
the PX4 command path.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field, replace
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from open_vi.domain import (
    FaultDatum,
    FaultSnapshot,
    TspiSnapshot,
    utc_now,
)

_HDG_UNKNOWN_CDEG = 65535.0
_TEMP_MIN_K = 150.0
_TEMP_MAX_K = 400.0
_HEARTBEAT_STALE_S = 10.0
FAULT_NS = uuid5(NAMESPACE_URL, "https://openautonomy.org/open-vi/px4")
# MAV_SYS_STATUS_SENSOR_* bits PX4 reports on SYS_STATUS.
# Bit, code, description, MA_FaultSeverityEnum severity.
#
# The severity is this adapter's judgement, which is where such a
# mapping belongs -- MAVLink reports a health bit, not a severity.
# WARNING is for what the airframe cannot fly without: attitude
# sources and motor outputs. CAUTION is for a degraded but survivable
# sensor. RC receiver is ADVISORY because an autonomous VI is not
# flying on it; losing it matters to a human operator, not to the
# vehicle's ability to continue.
_SENSOR_BITS: tuple[tuple[int, str, str, str], ...] = (
    (1, "SENSOR_3D_GYRO", "3D gyro unhealthy", "WARNING"),
    (2, "SENSOR_3D_ACCEL", "3D accel unhealthy", "WARNING"),
    (4, "SENSOR_3D_MAG", "3D mag unhealthy", "CAUTION"),
    (8, "SENSOR_BARO", "Absolute pressure unhealthy", "CAUTION"),
    (
        16,
        "SENSOR_DIFF_PRESSURE",
        "Differential pressure unhealthy",
        "CAUTION",
    ),
    (32, "SENSOR_GPS", "GPS unhealthy", "CAUTION"),
    (32768, "SENSOR_MOTOR_OUTPUTS", "Motor outputs unhealthy", "WARNING"),
    (65536, "SENSOR_RC_RECEIVER", "RC receiver unhealthy", "ADVISORY"),
    (2097152, "SENSOR_AHRS", "AHRS unhealthy", "WARNING"),
    (33554432, "SENSOR_BATTERY", "Battery unhealthy", "CAUTION"),
)


@dataclass
class MavCache:
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
    fault_first_seen: dict[str, str] = field(default_factory=dict)
    """FaultCode -> the DateTimeType when it first went unhealthy."""

    fault_occurrences: dict[str, int] = field(default_factory=dict)
    """FaultCode -> how many times it has gone unhealthy."""


def battery_duration_s(
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


def wind_ned(
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


def unhealthy_sensor_faults(
    present: int, enabled: int, health: int
) -> tuple[FaultSnapshot, ...]:
    """SET faults for sensors that are present, enabled, and not healthy."""
    faults: list[FaultSnapshot] = []
    watched = present & enabled
    for bit, code, description, severity in _SENSOR_BITS:
        if watched & bit and health & bit == 0:
            faults.append(
                FaultSnapshot(
                    fault_id=uuid5(FAULT_NS, code),
                    fault_code=code,
                    fault_state="SET",
                    fault_description=description,
                    severity=severity,
                )
            )
    return tuple(faults)


def ingest(cache: MavCache, msg: Any) -> int | None:
    """Update *cache* from one MAVLink message.

    Returns the ``MISSION_ITEM_REACHED`` seq when that is the type,
    else ``None``. Caller holds the session lock.
    """
    mtype = msg.get_type()
    if mtype == "HEARTBEAT":
        cache.last_heartbeat_mono = time.monotonic()
        cache.system_status = int(getattr(msg, "system_status", 0))
        base_mode = int(getattr(msg, "base_mode", 0))
        cache.base_mode = base_mode
        # MAV_MODE_FLAG_SAFETY_ARMED = 128
        cache.armed = bool(base_mode & 128)
        return None
    if mtype == "GLOBAL_POSITION_INT":
        cache.last_heartbeat_mono = time.monotonic()
        cache.lat_deg = msg.lat / 1e7
        cache.lon_deg = msg.lon / 1e7
        cache.alt_m = msg.alt / 1000.0
        cache.relative_alt_m = float(getattr(msg, "relative_alt", 0)) / 1000.0
        cache.vx_mps = msg.vx / 100.0
        cache.vy_mps = msg.vy / 100.0
        cache.vz_mps = msg.vz / 100.0
        hdg_cdeg = float(msg.hdg)
        if hdg_cdeg < _HDG_UNKNOWN_CDEG:
            heading = hdg_cdeg / 100.0
            cache.heading_deg = heading
            cache.compass_heading_deg = heading
        return None
    if mtype == "ATTITUDE":
        cache.last_heartbeat_mono = time.monotonic()
        cache.roll_rad = float(msg.roll)
        cache.pitch_rad = float(msg.pitch)
        cache.yaw_rad = float(msg.yaw)
        cache.ekf_yaw_deg = math.degrees(float(msg.yaw))
        return None
    if mtype == "VFR_HUD":
        airspeed = float(msg.airspeed)
        groundspeed = float(msg.groundspeed)
        cache.airspeed_mps = airspeed if math.isfinite(airspeed) else 0.0
        cache.groundspeed_mps = (
            groundspeed if math.isfinite(groundspeed) else 0.0
        )
        heading = float(msg.heading)
        cache.heading_deg = heading
        cache.compass_heading_deg = heading
        return None
    if mtype == "WIND_COV":
        cache.wind_north_mps = float(msg.wind_x)
        cache.wind_east_mps = float(msg.wind_y)
        return None
    if mtype == "WIND":
        coming_from = math.radians(float(msg.direction))
        wind_speed = float(msg.speed)
        cache.wind_north_mps = -wind_speed * math.cos(coming_from)
        cache.wind_east_mps = -wind_speed * math.sin(coming_from)
        return None
    if mtype == "SCALED_PRESSURE":
        press_pa = float(msg.press_abs) * 100.0
        if math.isfinite(press_pa) and press_pa > 0.0:
            cache.static_pressure_pa = press_pa
        temp_k = float(getattr(msg, "temperature", 0.0)) / 100.0
        temp_k += 273.15
        if _TEMP_MIN_K < temp_k < _TEMP_MAX_K:
            cache.temperature_k = temp_k
        return None
    if mtype == "SYS_STATUS":
        rem = int(getattr(msg, "battery_remaining", -1))
        cache.battery_remaining = rem if rem >= 0 else None
        cache.sensors_present = int(
            getattr(msg, "onboard_control_sensors_present", 0)
        )
        cache.sensors_enabled = int(
            getattr(msg, "onboard_control_sensors_enabled", 0)
        )
        cache.sensors_health = int(
            getattr(msg, "onboard_control_sensors_health", 0)
        )
        return None
    if mtype == "BATTERY_STATUS":
        rem = int(getattr(msg, "battery_remaining", -1))
        if rem >= 0:
            cache.battery_remaining = rem
        remaining_s = float(getattr(msg, "time_remaining", 0))
        if math.isfinite(remaining_s) and remaining_s > 0.0:
            cache.time_remaining_s = remaining_s
        current_ca = float(getattr(msg, "current_battery", -1))
        if math.isfinite(current_ca) and current_ca >= 0.0:
            cache.current_battery_a = current_ca / 100.0
        consumed = float(getattr(msg, "current_consumed", -1))
        if math.isfinite(consumed) and consumed >= 0.0:
            cache.current_consumed_mah = consumed
        return None
    if mtype == "MISSION_ITEM_REACHED":
        return int(getattr(msg, "seq", -1))
    return None


def link_fresh(cache: MavCache, *, connected: bool) -> bool:
    """True when a HEARTBEAT or position update is newer than 10 s."""
    if not connected:
        return False
    last = cache.last_heartbeat_mono
    if last <= 0.0:
        return False
    return (time.monotonic() - last) <= _HEARTBEAT_STALE_S


def freeze_home_hae(cache: MavCache, frozen: float | None) -> float | None:
    """Home HAE from AMSL minus relative-to-home, or *frozen*."""
    if frozen is not None:
        return frozen
    alt = cache.alt_m
    rel = cache.relative_alt_m
    if alt == 0.0 and rel == 0.0:
        return None
    return alt - rel


def tspi_from_cache(
    cache: MavCache,
    *,
    kollsman_hpa: float,
    component_id: UUID,
) -> TspiSnapshot:
    """Map the MAVLink cache into ``TspiSnapshot`` (degrees, NED, fuel)."""
    fuel = 85.0
    if cache.battery_remaining is not None:
        fuel = float(cache.battery_remaining)
    heading_rad = math.radians(cache.heading_deg)
    duration_s = battery_duration_s(
        time_remaining_s=cache.time_remaining_s,
        battery_remaining=cache.battery_remaining,
        current_battery_a=cache.current_battery_a,
        current_consumed_mah=cache.current_consumed_mah,
    )
    return TspiSnapshot(
        latitude_deg=cache.lat_deg,
        longitude_deg=cache.lon_deg,
        altitude_m=cache.alt_m,
        north_speed_mps=cache.vx_mps,
        east_speed_mps=cache.vy_mps,
        down_speed_mps=cache.vz_mps,
        yaw_rad=cache.yaw_rad,
        pitch_rad=cache.pitch_rad,
        roll_rad=cache.roll_rad,
        indicated_baro_altitude_m=cache.alt_m,
        kollsman_hpa=kollsman_hpa,
        true_airspeed_mps=cache.airspeed_mps,
        calibrated_airspeed_mps=cache.airspeed_mps,
        fuel_percent=fuel,
        fuel_duration_s=duration_s,
        magnetic_heading_rad=heading_rad,
        component_id=component_id,
        component_label="px4",
        component_state="OPERATIONAL",
    )


def track_faults(
    cache: MavCache,
    faults: tuple[FaultSnapshot, ...],
    *,
    evidence: FaultDatum | None = None,
) -> tuple[FaultSnapshot, ...]:
    """Stamp *faults* with their detection time and occurrence count.

    Tables 1-4 and 1-5 require ``DetectionTime`` and
    ``FaultCodeCount``, and neither can be derived from one sample.
    A-GRA says ``DetectionTime`` "does not indicate the time the fault
    was transmitted", so re-stamping it every tick would read as
    continuous re-detection; it is recorded once, when the code sets,
    and held until the code clears. ``FaultCodeCount`` counts those
    clear-to-set transitions for the same reason: a sensor that flaps
    is several occurrences, one that stays unhealthy is one.

    A code absent from *faults* is treated as cleared, so the next
    time it sets it gets a fresh detection time and a higher count.

    Mutates *cache*'s two tracking maps. The caller holds the lock.
    """
    active = {fault.fault_code for fault in faults}
    for code in [c for c in cache.fault_first_seen if c not in active]:
        del cache.fault_first_seen[code]
    out: list[FaultSnapshot] = []
    for fault in faults:
        code = fault.fault_code
        if code not in cache.fault_first_seen:
            cache.fault_first_seen[code] = utc_now()
            cache.fault_occurrences[code] = (
                cache.fault_occurrences.get(code, 0) + 1
            )
        out.append(
            replace(
                fault,
                detection_time=cache.fault_first_seen[code],
                fault_code_count=cache.fault_occurrences[code],
                fault_data=(evidence,) if evidence else fault.fault_data,
            )
        )
    return tuple(out)


def sensor_faults(cache: MavCache) -> tuple[FaultSnapshot, ...]:
    """SET faults from the last SYS_STATUS bitfields, with history.

    ``FaultData`` carries the SYS_STATUS health bitfield, which is the
    evidence each fault was derived from and exactly what A-GRA
    describes that field as being for: key/value data "to support
    fault isolation and helps to minimize false alarms".

    Mutates *cache* via :func:`track_faults`; caller holds the lock.
    """
    return track_faults(
        cache,
        unhealthy_sensor_faults(
            cache.sensors_present,
            cache.sensors_enabled,
            cache.sensors_health,
        ),
        evidence=FaultDatum(
            key="SYS_STATUS.onboard_control_sensors_health",
            value=hex(cache.sensors_health),
            data_format="MAVLINK_SENSOR_BITMASK_HEX",
        ),
    )


def link_down_fault() -> FaultSnapshot:
    """SET fault for a stale or missing MAVLink session.

    ``FAILED`` rather than ``WARNING``: with no link the VI cannot
    command or observe the airframe at all, so the interface has not
    degraded, it has stopped.
    """
    return FaultSnapshot(
        fault_id=uuid5(FAULT_NS, "PX4_LINK_DOWN"),
        fault_code="PX4_LINK_DOWN",
        fault_state="SET",
        fault_description="PX4 MAVLink link is down",
        severity="FAILED",
    )
