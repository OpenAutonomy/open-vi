"""Internal vehicle face used by the Isolator (no UCI / no MAVLink)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from uuid import UUID

from open_vi.domain import (
    CommandResult,
    FaultSnapshot,
    FlightActivitySnapshot,
    FlightCommandRequest,
    PlatformSnapshot,
    ServiceStatusSnapshot,
    SubsystemStatusSnapshot,
    TspiSnapshot,
)


class PlatformPort(ABC):
    """Vehicle backend API — Stub, PX4, X-Plane, etc."""

    @abstractmethod
    def snapshot(self) -> PlatformSnapshot:
        """Return current control offer and readiness."""

    @abstractmethod
    def submit_flight_command(self, cmd: FlightCommandRequest) -> CommandResult:
        """Accept or reject a flight capability command."""

    def poll_command_updates(self) -> list[tuple[UUID, CommandResult]]:
        """Return newly reached terminal command states since the last poll.

        Used by the Isolator tick to publish ``MA_FlightCommandStatus``
        when a previously accepted command finishes (``COMPLETED``).
        Default is no updates.
        """
        return []

    @abstractmethod
    def active_flight_activity(self) -> FlightActivitySnapshot | None:
        """Return the current flight activity, if any."""

    @abstractmethod
    def get_vehicle_state(self) -> TspiSnapshot:
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
    def apply_system_management(self, *, qnh_kpa: float | None = None) -> str:
        """Apply SystemManagementRequest (QNH). Return COMPLETED or REJECTED."""

    def close(self) -> None:
        """Release backend resources. Default is a no-op."""
        return
