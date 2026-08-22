"""Service, subsystem, and fault snapshots for Isolator status outs."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ServiceStatusSnapshot:
    """VI ServiceStatus heartbeat fields."""

    service_id: UUID
    service_label: str = "open-vi"
    service_version: str = "0.4.0"
    time_up: str = "PT0S"
    service_state: str = "NORMAL"


@dataclass(frozen=True)
class SubsystemStatusSnapshot:
    """SubsystemStatus report fields."""

    subsystem_id: UUID
    subsystem_label: str = "flight"
    subsystem_state: str = "OPERATE"
    model: str = "open-vi-stub"
    software_version: str = "0.4.0"


@dataclass(frozen=True)
class FaultSnapshot:
    """Single MA_Fault FaultInformation entry."""

    fault_id: UUID
    fault_code: str = "NO_FAULT"
    fault_state: str = "CLEARED"
    fault_description: str = "No active faults"
