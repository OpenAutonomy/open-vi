"""Internal vehicle face used by the Isolator (no UCI / no MAVLink)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from uuid import UUID, uuid4


@dataclass(frozen=True)
class ControlOffer:
    """Control modes the platform is willing to advertise to MA."""

    capability_types: tuple[str, ...] = (
        "HSA_CSA",
        "WAYPOINT_FOLLOWING",
        "CURVE_FOLLOWING",
    )
    capability_label: str = "flight-capability"
    accepted_interfaces: tuple[str, ...] = ("CAPABILITY_COMMAND",)


@dataclass(frozen=True)
class ControlReadiness:
    """Whether MA may currently command the offered flight capability."""

    available: bool = True
    availability: str = "AVAILABLE"
    reason: str | None = None


@dataclass
class PlatformSnapshot:
    """Combined view polled each Isolator tick."""

    offer: ControlOffer = field(default_factory=ControlOffer)
    readiness: ControlReadiness = field(default_factory=ControlReadiness)


@dataclass(frozen=True)
class Waypoint:
    """Simplified geodetic waypoint extracted from a FlightCommand route."""

    latitude_deg: float
    longitude_deg: float
    altitude_m: float | None = None


@dataclass(frozen=True)
class FlightCommandRequest:
    """Internal command submitted by the Isolator (not UCI)."""

    command_id: UUID
    capability_id: UUID
    command_state: str  # NEW | UPDATE | CANCEL
    mode: str | None  # WAYPOINT_FOLLOWING | HSA_CSA | CURVE_FOLLOWING | None
    waypoints: tuple[Waypoint, ...] = ()
    choice: str = "Capability"  # Capability | Activity


@dataclass(frozen=True)
class CommandResult:
    """Accept/reject decision from the platform."""

    processing_state: str  # ACCEPTED | REJECTED | CANCELED | RECEIVED
    activity_id: UUID | None = None
    new_activity: bool = True
    reason: str | None = None
    reason_description: str | None = None


@dataclass(frozen=True)
class FlightActivitySnapshot:
    """Active flight activity reported toward MA_FlightActivity."""

    activity_id: UUID
    capability_id: UUID
    activity_state: str = "ACTIVE_UNCONSTRAINED"
    interactive: bool = True


@dataclass(frozen=True)
class TsipSnapshot:
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


@dataclass(frozen=True)
class ServiceStatusSnapshot:
    """VI ServiceStatus heartbeat fields."""

    service_id: UUID
    service_label: str = "open-vi"
    service_version: str = "0.1.0"
    time_up: str = "PT0S"
    service_state: str = "NORMAL"


@dataclass(frozen=True)
class SubsystemStatusSnapshot:
    """SubsystemStatus report fields."""

    subsystem_id: UUID
    subsystem_label: str = "flight"
    subsystem_state: str = "OPERATE"
    model: str = "open-vi-stub"
    software_version: str = "0.1.0"


@dataclass(frozen=True)
class FaultSnapshot:
    """Single MA_Fault FaultInformation entry."""

    fault_id: UUID
    fault_code: str = "NO_FAULT"
    fault_state: str = "CLEARED"
    fault_description: str = "No active faults"


@dataclass(frozen=True)
class RouteActivationRequest:
    """Internal route activation (BySubPlan or ByMissionPlan)."""

    command_id: UUID
    mission_plan_id: UUID
    route_plan_id: UUID
    command_type: str  # PREPARE_FOR_UPLOAD | UPLOAD | …
    command_state: str = "NEW"


@dataclass(frozen=True)
class RouteActivationResult:
    """Accept/reject + plan-state outcome for a route activation command."""

    processing_state: str  # ACCEPTED | REJECTED
    plan_state: str  # PlanActivationStateEnum terminal (or failed)
    progress_state: str | None = None  # mid-state for Loose 2-status pair
    emit_pair: bool = True  # False → single status (DEACTIVATE Loose)
    reason: str | None = None
    reason_description: str | None = None


@dataclass(frozen=True)
class StoredRoutePlan:
    """Route plan bytes retained after MA_RoutePlan ingest."""

    route_plan_id: UUID
    xml: str
    sha256_hex: str
    mission_plan_id: UUID | None = None
    plan_state: str = "READY_FOR_UPLOAD"


class PlatformPort(ABC):
    """Vehicle backend API — Stub, PX4, X-Plane, etc."""

    @abstractmethod
    def snapshot(self) -> PlatformSnapshot:
        """Return current control offer and readiness."""

    @abstractmethod
    def submit_flight_command(self, cmd: FlightCommandRequest) -> CommandResult:
        """Accept or reject a flight capability command."""

    @abstractmethod
    def active_flight_activity(self) -> FlightActivitySnapshot | None:
        """Return the current flight activity, if any."""

    @abstractmethod
    def get_vehicle_state(self) -> TsipSnapshot:
        """Return current TSPI / navigation / weather / component state."""

    @abstractmethod
    def get_service_status(self) -> ServiceStatusSnapshot:
        """Return VI service heartbeat status."""

    @abstractmethod
    def get_subsystem_status(self) -> SubsystemStatusSnapshot:
        """Return primary subsystem status."""

    @abstractmethod
    def get_faults(self) -> tuple[FaultSnapshot, ...]:
        """Return current faults (stub may return a cleared sentinel)."""

    @abstractmethod
    def handle_route_activation(
        self, req: RouteActivationRequest
    ) -> RouteActivationResult:
        """Advance route lifecycle upload → prepare → activate → deactivate."""

    @abstractmethod
    def store_route_plan(
        self,
        route_plan_id: UUID,
        xml: str,
        *,
        mission_plan_id: UUID | None = None,
    ) -> StoredRoutePlan:
        """Retain inbound MA_RoutePlan content for File* / upload."""

    @abstractmethod
    def get_stored_route(self, route_plan_id: UUID) -> StoredRoutePlan | None:
        """Return a previously stored route plan, if any."""

    @abstractmethod
    def apply_system_management(self, *, qnh_kpa: float | None = None) -> str:
        """Apply SystemManagementRequest (QNH). Return COMPLETED or REJECTED."""
