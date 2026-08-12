"""PlatformPort and vehicle backends."""

from __future__ import annotations

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
from open_vi.platform.px4 import DEFAULT_MAVLINK_URL, Px4MavlinkAdapter
from open_vi.platform.stub import StubPlatform

__all__ = [
    "CommandResult",
    "ControlOffer",
    "ControlReadiness",
    "DEFAULT_MAVLINK_URL",
    "FaultSnapshot",
    "FlightActivitySnapshot",
    "FlightCommandRequest",
    "PlatformPort",
    "PlatformSnapshot",
    "Px4MavlinkAdapter",
    "RouteActivationRequest",
    "RouteActivationResult",
    "ServiceStatusSnapshot",
    "StoredRoutePlan",
    "StubPlatform",
    "SubsystemStatusSnapshot",
    "TsipSnapshot",
    "Waypoint",
    "make_platform",
]


def make_platform(
    name: str = "stub",
    *,
    mavlink_url: str | None = None,
    autoconnect: bool = True,
) -> PlatformPort:
    """Construct a vehicle backend by name (``stub`` or ``px4``)."""
    key = name.strip().lower()
    if key == "stub":
        return StubPlatform()
    if key == "px4":
        return Px4MavlinkAdapter(
            connection_url=mavlink_url,
            autoconnect=autoconnect,
        )
    raise ValueError(f"Unknown platform {name!r}; expected stub|px4")
