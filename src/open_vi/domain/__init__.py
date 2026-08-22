"""Internal language: values only. No XML, no bus, no Isolator tick.

Degrees here; radians begin at the codec boundary. Re-exports flight, TSPI,
status, route, airfield, and control types used by codec, Isolator,
and PlatformPort.
"""

from open_vi.domain.airfield import HomeAirfield, home_airfield_from_tspi
from open_vi.domain.control import (
    ControlOffer,
    ControlReadiness,
    FlightModeProfile,
    PlatformSnapshot,
    redact_control_offer,
)
from open_vi.domain.flight import (
    CommandResult,
    FlightActivitySnapshot,
    FlightCommandRequest,
    HsaCsaSetpoint,
    Waypoint,
    finite_waypoint_geometry,
    is_live_activity,
    validate_hsa_setpoint,
    validate_waypoint_path,
)
from open_vi.domain.route import (
    PlanExecutionSnapshot,
    RouteActivationRequest,
    RouteActivationResult,
    StoredRoutePlan,
)
from open_vi.domain.status import (
    FaultSnapshot,
    ServiceStatusSnapshot,
    SubsystemStatusSnapshot,
)
from open_vi.domain.tspi import TspiSnapshot

__all__ = [
    "CommandResult",
    "ControlOffer",
    "ControlReadiness",
    "FaultSnapshot",
    "FlightModeProfile",
    "FlightActivitySnapshot",
    "FlightCommandRequest",
    "HomeAirfield",
    "HsaCsaSetpoint",
    "PlanExecutionSnapshot",
    "PlatformSnapshot",
    "RouteActivationRequest",
    "RouteActivationResult",
    "ServiceStatusSnapshot",
    "StoredRoutePlan",
    "SubsystemStatusSnapshot",
    "TspiSnapshot",
    "Waypoint",
    "finite_waypoint_geometry",
    "home_airfield_from_tspi",
    "is_live_activity",
    "redact_control_offer",
    "validate_hsa_setpoint",
    "validate_waypoint_path",
]
