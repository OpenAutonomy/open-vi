"""Service, subsystem, and fault snapshots for Isolator status outs."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class ServiceStatusSnapshot:
    """VI ServiceStatus heartbeat fields."""

    service_id: UUID
    service_label: str = "open-vi"
    service_version: str = "0.6.0"
    time_up: str = "PT0S"
    service_state: str = "NORMAL"


@dataclass(frozen=True)
class SubsystemStatusSnapshot:
    """SubsystemStatus report fields."""

    subsystem_id: UUID
    subsystem_label: str = "flight"
    subsystem_state: str = "OPERATE"
    model: str = "open-vi-stub"
    software_version: str = "0.6.0"


@dataclass(frozen=True)
class FaultDatum:
    """One ``FaultData`` key/value pair.

    A-GRA describes these as "key/value pairs with format and unit
    indicated for the data value", supporting fault isolation and
    minimising false alarms. ``Key``, ``Value`` and ``Format`` are
    required by the schema; ``Units`` is optional and omitted for a
    dimensionless value such as a bitmask.
    """

    key: str
    value: str
    data_format: str
    units: str | None = None


@dataclass(frozen=True)
class FaultSnapshot:
    """Single MA_Fault FaultInformation entry.

    Tables 1-4 and 1-5 require nine fields of ``MA_Fault``, which are
    exactly the members of A-GRA's ``MA_SubsystemFaultType``. The
    optional ones are left unset when the platform has no truthful
    value: a ``CLEARED`` / ``NO_FAULT`` sentinel has no detection time
    and no occurrence count, and reporting one would be worse than
    reporting none.
    """

    fault_id: UUID
    fault_code: str = "NO_FAULT"
    fault_state: str = "CLEARED"
    fault_description: str = "No active faults"
    severity: str = "NOMINAL"
    """``MA_FaultSeverityEnum``: NOMINAL, ADVISORY, CAUTION, WARNING,
    FAILED. NOMINAL suits the no-fault sentinel."""

    detection_time: str | None = None
    """When the fault was *detected*. A-GRA is explicit that this "does
    not indicate the time the fault was transmitted", so a producer
    records the moment the fault appeared and keeps it."""

    fault_code_count: int | None = None
    """Occurrences of this code in a set state. A sensor that flaps is
    several occurrences; one that stays unhealthy is one."""

    subsystem_id: UUID | None = None
    service_id: UUID | None = None
    fault_data: tuple[FaultDatum, ...] = ()
