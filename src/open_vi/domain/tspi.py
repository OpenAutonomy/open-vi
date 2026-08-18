"""Internal vehicle kinematics / endurance for TSPI outs."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass(frozen=True)
class TspiSnapshot:
    """Internal vehicle kinematics / endurance for TSPI outs."""

    latitude_deg: float = 38.8895
    longitude_deg: float = -77.0353
    altitude_m: float = 100.0
    north_speed_mps: float = 0.0
    east_speed_mps: float = 0.0
    down_speed_mps: float = 0.0
    yaw_rad: float = 0.0
    pitch_rad: float = 0.0
    roll_rad: float = 0.0
    yaw_rate_rps: float = 0.0
    pitch_rate_rps: float = 0.0
    roll_rate_rps: float = 0.0
    north_accel_mps2: float = 0.0
    east_accel_mps2: float = 0.0
    down_accel_mps2: float = 0.0
    wander_angle_rad: float = 0.0
    magnetic_heading_rad: float = 0.0
    indicated_baro_altitude_m: float = 100.0
    kollsman_hpa: float = 1013.25
    true_airspeed_mps: float = 0.0
    calibrated_airspeed_mps: float = 0.0
    mach: float = 0.0
    fuel_percent: float = 85.0
    wind_north_mps: float = 1.0
    wind_east_mps: float = 0.5
    navigation_solution: str = "BLENDED"
    component_id: UUID = field(default_factory=uuid4)
    component_label: str = "engine"
    component_state: str = "OPERATIONAL"
