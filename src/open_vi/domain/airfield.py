"""Home airfield for Query Airfield Update (not UCI)."""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass

from open_vi.domain.flight import Waypoint
from open_vi.domain.tspi import TspiSnapshot
from open_vi.identity import SystemIdentity

_RUNWAY_LENGTH_M = 1500.0
_DIRECTION_DEG = 90.0
_METERS_PER_DEG_LAT = 111_320.0


@dataclass(frozen=True)
class HomeAirfield:
    """Self-reported home field, runway, and linked TO/L plan ids."""

    airfield_id: uuid.UUID
    report_id: uuid.UUID
    runway_id: uuid.UUID
    takeoff_route_id: uuid.UUID
    landing_route_id: uuid.UUID
    direction_deg: float
    available_length_m: float
    takeoff_start: Waypoint
    takeoff_end: Waypoint
    landing_start: Waypoint
    landing_end: Waypoint

    @property
    def takeoff_path(self) -> tuple[Waypoint, ...]:
        """Runway start to far end."""
        return (self.takeoff_start, self.takeoff_end)

    @property
    def landing_path(self) -> tuple[Waypoint, ...]:
        """Far end back to runway start."""
        return (self.landing_start, self.landing_end)

    @property
    def route_ids(self) -> tuple[uuid.UUID, uuid.UUID]:
        """Takeoff then landing plan ids."""
        return (self.takeoff_route_id, self.landing_route_id)


def home_airfield_from_tspi(
    identity: SystemIdentity,
    tspi: TspiSnapshot,
    *,
    length_m: float = _RUNWAY_LENGTH_M,
    direction_deg: float = _DIRECTION_DEG,
) -> HomeAirfield:
    """Build a home field at the current TSPI position.

    One runway along *direction_deg*. Takeoff is start→end; landing
    is the reverse. Plan and runway ids are stable for *identity*.
    """
    start = Waypoint(
        latitude_deg=tspi.latitude_deg,
        longitude_deg=tspi.longitude_deg,
        altitude_m=tspi.altitude_m,
    )
    heading = math.radians(direction_deg)
    dlat = (length_m * math.cos(heading)) / _METERS_PER_DEG_LAT
    meters_per_deg_lon = _METERS_PER_DEG_LAT * math.cos(
        math.radians(tspi.latitude_deg)
    )
    dlon = (length_m * math.sin(heading)) / meters_per_deg_lon
    end = Waypoint(
        latitude_deg=tspi.latitude_deg + dlat,
        longitude_deg=tspi.longitude_deg + dlon,
        altitude_m=tspi.altitude_m,
    )
    return HomeAirfield(
        airfield_id=identity.uuid,
        report_id=uuid.uuid5(identity.uuid, "home-airfield-report"),
        runway_id=uuid.uuid5(identity.uuid, "home-runway"),
        takeoff_route_id=uuid.uuid5(identity.uuid, "home-takeoff"),
        landing_route_id=uuid.uuid5(identity.uuid, "home-landing"),
        direction_deg=direction_deg,
        available_length_m=length_m,
        takeoff_start=start,
        takeoff_end=end,
        landing_start=end,
        landing_end=start,
    )
