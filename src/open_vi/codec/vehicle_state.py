"""Builders for vehicle-state / TSPI outs."""

from __future__ import annotations

import math
from uuid import UUID
from xml.etree import ElementTree as ET

from open_vi.codec.geo import deg_to_rad, format_uci_angle
from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.xmlutil import (
    el,
    id_type,
    message_envelope,
    system_id,
    tostring,
    utc_now,
)
from open_vi.domain import TspiSnapshot
from open_vi.identity import SystemIdentity


def _num(value: float) -> str:
    if not math.isfinite(value):
        return "0"
    return format_uci_angle(value)


def _angle(value: float) -> str:
    """A-GRA AngleType is [-π, π]."""
    if not math.isfinite(value):
        return "0"
    wrapped = (value + math.pi) % (2 * math.pi) - math.pi
    return format_uci_angle(wrapped)


def _cov_pp() -> ET.Element:
    return el(
        "PositionPositionCovariance",
        el("PnPn", text="1"),
        el("PnPe", text="0"),
        el("PnPd", text="0"),
        el("PePe", text="1"),
        el("PePd", text="0"),
        el("PdPd", text="1"),
    )


def _cov_pv() -> ET.Element:
    return el(
        "PositionVelocityCovariance",
        el("PnVn", text="0"),
        el("PnVe", text="0"),
        el("PnVd", text="0"),
        el("PeVn", text="0"),
        el("PeVe", text="0"),
        el("PeVd", text="0"),
        el("PdVn", text="0"),
        el("PdVe", text="0"),
        el("PdVd", text="0"),
    )


def _cov_vv() -> ET.Element:
    return el(
        "VelocityVelocityCovariance",
        el("VnVn", text="1"),
        el("VnVe", text="0"),
        el("VnVd", text="0"),
        el("VeVe", text="1"),
        el("VeVd", text="0"),
        el("VdVd", text="1"),
    )


def build_position_report_detailed(
    identity: SystemIdentity,
    state: TspiSnapshot,
    *,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build MA_PositionReportDetailed (radians + NED + covariances)."""
    now = utc_now()
    lat = deg_to_rad(state.latitude_deg)
    lon = deg_to_rad(state.longitude_deg)
    absolute = el(
        "AbsolutePoint",
        el("Latitude", text=_num(lat)),
        el("Longitude", text=_num(lon)),
        el("Altitude", text=_num(state.altitude_m)),
        el("Timestamp", text=now),
    )
    kinematics = el(
        "Kinematics",
        el("Position", absolute),
        el(
            "Velocity",
            el("NorthSpeed", text=_num(state.north_speed_mps)),
            el("EastSpeed", text=_num(state.east_speed_mps)),
            el("DownSpeed", text=_num(state.down_speed_mps)),
        ),
        el(
            "AirData",
            el(
                "IndicatedBaroAltitude",
                text=_num(state.indicated_baro_altitude_m),
            ),
            el("Kollsman", text=_num(state.kollsman_hpa)),
            el("TrueAirspeed", text=_num(state.true_airspeed_mps)),
            el(
                "CalibratedAirspeed",
                text=_num(state.calibrated_airspeed_mps),
            ),
            el("Mach", text=_num(state.mach)),
        ),
        el(
            "Acceleration",
            el("NorthAcceleration", text=_num(state.north_accel_mps2)),
            el("EastAcceleration", text=_num(state.east_accel_mps2)),
            el("DownAcceleration", text=_num(state.down_accel_mps2)),
        ),
        el(
            "Orientation",
            el("Yaw", text=_angle(state.yaw_rad)),
            el("Pitch", text=_angle(state.pitch_rad)),
            el("Roll", text=_angle(state.roll_rad)),
        ),
        el("WanderAngle", text=_angle(state.wander_angle_rad)),
        el("MagneticHeading", text=_angle(state.magnetic_heading_rad)),
        el(
            "OrientationRate",
            el("YawRate", text=_num(state.yaw_rate_rps)),
            el("PitchRate", text=_num(state.pitch_rate_rps)),
            el("RollRate", text=_num(state.roll_rate_rps)),
        ),
        el(
            "OrientationAcceleration",
            el("YawAccel", text="0"),
            el("PitchAccel", text="0"),
            el("RollAccel", text="0"),
        ),
    )
    report = el(
        "PositionReportData",
        el("PositionSource", system_id(identity)),
        el("NavigationSolutionState", text=state.navigation_solution),
        kinematics,
        el("KinematicsError", _cov_pp(), _cov_pv(), _cov_vv()),
    )
    data = el("MessageData", report)
    root = message_envelope(
        "MA_PositionReportDetailed",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_navigation_report(
    identity: SystemIdentity,
    state: TspiSnapshot,
    *,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build NavigationReport with fuel endurance percent."""
    data = el(
        "MessageData",
        system_id(identity),
        el("Source", text="ACTUAL"),
        el("ContingencyLevel", text="NORMAL"),
        el("Endurance", el("Percent", text=_num(state.fuel_percent))),
    )
    root = message_envelope(
        "NavigationReport",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_weather_observation(
    identity: SystemIdentity,
    state: TspiSnapshot,
    *,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build WeatherObservation with platform wind (Source=OTHER)."""
    now = utc_now()
    lat = deg_to_rad(state.latitude_deg)
    lon = deg_to_rad(state.longitude_deg)
    point = el(
        "ObservationPoint",
        el("Latitude", text=_num(lat)),
        el("Longitude", text=_num(lon)),
        el("Altitude", text=_num(state.altitude_m)),
        el("Timestamp", text=now),
    )
    wind = el(
        "WindData",
        el(
            "WindChoice",
            el(
                "WindVelocity",
                el("NorthSpeed", text=_num(state.wind_north_mps)),
                el("EastSpeed", text=_num(state.wind_east_mps)),
            ),
        ),
    )
    weather = el("WeatherData", el("Source", text="OTHER"), wind)
    data = el(
        "MessageData",
        system_id(identity, tag="ObservingSystemID"),
        point,
        weather,
    )
    root = message_envelope(
        "WeatherObservation",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_component_status(
    identity: SystemIdentity,
    state: TspiSnapshot,
    *,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
    component_id: UUID | None = None,
) -> bytes:
    """Build ComponentStatus for a single vehicle component."""
    cid = component_id or state.component_id
    status = el(
        "ComponentStatus",
        id_type("ComponentID", cid, state.component_label),
        el("ComponentState", text=state.component_state),
    )
    data = el("MessageData", status)
    root = message_envelope(
        "ComponentStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)
