"""Default :class:`PlatformPort` for tests and ``open-vi``.

Deterministic in-process state: no MAVLink, no motion. Isolator and
the codec never import this module — ``make_platform()`` and tests
construct :class:`StubPlatform` directly. Accepts all three A-GRA
modes. ``inject_contingency`` is Stub-only and is not on the port.
"""

from __future__ import annotations

import time
from dataclasses import replace
from uuid import UUID, uuid4

from open_vi.domain import (
    CommandResult,
    ControlOffer,
    ControlReadiness,
    FaultSnapshot,
    FlightActivitySnapshot,
    FlightCommandRequest,
    PlatformSnapshot,
    ServiceStatusSnapshot,
    SubsystemStatusSnapshot,
    TspiSnapshot,
    is_live_activity,
)
from open_vi.platform.port import PlatformPort

_ACCEPTED_MODES = frozenset(
    {"WAYPOINT_FOLLOWING", "HSA_CSA", "CURVE_FOLLOWING"}
)


class StubPlatform(PlatformPort):
    """Fixed offer, TSPI, and status; accept/reject without a vehicle.

    Default offer is HSA_CSA, WAYPOINT_FOLLOWING, and CURVE_FOLLOWING,
    all ``AVAILABLE``. ``submit_flight_command`` accepts immediately
    and returns ``ACTIVE_UNCONSTRAINED``. Tests call
    :meth:`complete_flight_command` when they need a later
    ``COMPLETED``. :meth:`set_readiness` and :meth:`inject_contingency`
    are harness hooks, not Isolator ICD steps.
    """

    def __init__(
        self,
        *,
        offer: ControlOffer | None = None,
        readiness: ControlReadiness | None = None,
        vehicle_state: TspiSnapshot | None = None,
        service_id: UUID | None = None,
        subsystem_id: UUID | None = None,
    ) -> None:
        self._offer = offer or ControlOffer()
        self._readiness = readiness or ControlReadiness()
        self._activity: FlightActivitySnapshot | None = None
        self._commands: dict[UUID, str] = {}
        self._pending_updates: list[tuple[UUID, CommandResult]] = []
        self._vehicle_state = vehicle_state or TspiSnapshot(
            component_id=uuid4()
        )
        self._service_id = service_id or uuid4()
        self._subsystem_id = subsystem_id or uuid4()
        self._fault_id = uuid4()
        self._subsystem_state = "OPERATE"
        self._faults: tuple[FaultSnapshot, ...] = (
            FaultSnapshot(fault_id=self._fault_id),
        )
        self._started = time.monotonic()

    def snapshot(self) -> PlatformSnapshot:
        """Current offer and readiness. Used by advertise and the tick."""
        return PlatformSnapshot(offer=self._offer, readiness=self._readiness)

    def set_readiness(self, readiness: ControlReadiness) -> None:
        """Test helper: change availability without rebuilding Isolator."""
        self._readiness = readiness

    def submit_flight_command(self, cmd: FlightCommandRequest) -> CommandResult:
        """Accept Capability NEW when idle, CANCEL, or Activity UPDATE.

        Rejects when readiness is unavailable, Capability NEW arrives
        while an activity is live, the Activity is not an UPDATE
        against the live activity, or the mode is unknown. Unlike PX4,
        waypoints are not required and nothing is uploaded to a vehicle.
        """
        if not self._readiness.available:
            return CommandResult(
                processing_state="REJECTED",
                reason="CAPABILITY_UNAVAILABLE",
                reason_description="Flight capability not available",
            )
        if cmd.choice == "Activity":
            return self._submit_activity(cmd)
        if cmd.command_state == "CANCEL":
            if cmd.command_id in self._commands:
                self._commands[cmd.command_id] = "CANCELED"
                self._activity = None
                self._pending_updates = [
                    item
                    for item in self._pending_updates
                    if item[0] != cmd.command_id
                ]
                return CommandResult(processing_state="CANCELED")
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description="Unknown command id for CANCEL",
            )
        if cmd.command_state != "NEW":
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description=(
                    "Capability commands require CommandState NEW or CANCEL"
                ),
            )
        if is_live_activity(self._activity):
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description=(
                    "Capability NEW is not allowed while an activity "
                    "is live; use Activity UPDATE"
                ),
            )
        if cmd.mode not in _ACCEPTED_MODES:
            return CommandResult(
                processing_state="REJECTED",
                reason="CAPABILITY_UNAVAILABLE",
                reason_description=(
                    "Stub accepts WAYPOINT_FOLLOWING, HSA_CSA, "
                    f"CURVE_FOLLOWING; got {cmd.mode}"
                ),
            )
        activity_id = uuid4()
        self._activity = FlightActivitySnapshot(
            activity_id=activity_id,
            capability_id=cmd.capability_id,
            activity_state="ACTIVE_UNCONSTRAINED",
            interactive=True,
        )
        self._commands[cmd.command_id] = "ACCEPTED"
        return CommandResult(
            processing_state="ACCEPTED",
            activity_id=activity_id,
            new_activity=True,
        )

    def _submit_activity(self, cmd: FlightCommandRequest) -> CommandResult:
        """Keep the live activity_id; reject NEW, CANCEL, and unknown ids."""
        if cmd.command_state != "UPDATE":
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description=(
                    "Activity commands require CommandState UPDATE"
                ),
            )
        if (
            not is_live_activity(self._activity)
            or cmd.activity_id != self._activity.activity_id
        ):
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description="Unknown or idle ActivityID",
            )
        if cmd.mode not in _ACCEPTED_MODES:
            return CommandResult(
                processing_state="REJECTED",
                reason="CAPABILITY_UNAVAILABLE",
                reason_description=(
                    "Stub accepts WAYPOINT_FOLLOWING, HSA_CSA, "
                    f"CURVE_FOLLOWING; got {cmd.mode}"
                ),
            )
        self._commands[cmd.command_id] = "ACCEPTED"
        return CommandResult(
            processing_state="ACCEPTED",
            activity_id=self._activity.activity_id,
            new_activity=False,
        )

    def complete_flight_command(
        self, command_id: UUID | None = None
    ) -> UUID | None:
        """Queue ``COMPLETED`` for Isolator's next ``poll_command_updates``.

        *command_id* defaults to the first ``ACCEPTED`` command.
        Returns that id, or ``None`` if nothing was live. Also marks
        the current activity ``COMPLETED``.
        """
        cid = command_id
        if cid is None:
            cid = next(
                (
                    key
                    for key, state in self._commands.items()
                    if state == "ACCEPTED"
                ),
                None,
            )
        if cid is None or self._commands.get(cid) != "ACCEPTED":
            return None
        self._commands[cid] = "COMPLETED"
        activity_id = None
        if self._activity is not None:
            activity_id = self._activity.activity_id
            self._activity = replace(self._activity, activity_state="COMPLETED")
        self._pending_updates.append(
            (
                cid,
                CommandResult(
                    processing_state="COMPLETED",
                    activity_id=activity_id,
                ),
            )
        )
        return cid

    def poll_command_updates(self) -> list[tuple[UUID, CommandResult]]:
        """Drain terminal states queued by :meth:`complete_flight_command`."""
        updates = list(self._pending_updates)
        self._pending_updates.clear()
        return updates

    def active_flight_activity(self) -> FlightActivitySnapshot | None:
        """Current activity, or ``None`` if idle or canceled."""
        return self._activity

    def get_vehicle_state(self) -> TspiSnapshot:
        """Fixed TSPI snapshot (constructor or default pose)."""
        return self._vehicle_state

    def get_service_status(self) -> ServiceStatusSnapshot:
        """VI service heartbeat fields for this process."""
        secs = max(0, int(time.monotonic() - self._started))
        return ServiceStatusSnapshot(
            service_id=self._service_id,
            time_up=f"PT{secs}S",
        )

    def get_subsystem_status(self) -> SubsystemStatusSnapshot:
        """Primary subsystem row. ``DEGRADED`` after ``SENSOR_FAILURE``."""
        return SubsystemStatusSnapshot(
            subsystem_id=self._subsystem_id,
            subsystem_state=self._subsystem_state,
        )

    def get_faults(self) -> tuple[FaultSnapshot, ...]:
        """Current faults. Default is a cleared sentinel."""
        return self._faults

    def inject_contingency(self, kind: str) -> None:
        """Apply a Loose Direction1 contingency. Stub/harness only.

        ``MECHANICAL_DAMAGE`` sets a fault.
        ``SENSOR_FAILURE`` sets a fault and ``DEGRADED``.
        ``COLLISION_AVOIDANCE`` marks the offer
        ``UNAVAILABLE`` / ``CONSTRAINT_COLLISION_AVOIDANCE``.
        ``CLEAR`` restores operate, a cleared fault, and
        ``AVAILABLE``. Other *kind* values raise ``ValueError``.

        Isolator publishes the matching outs via
        ``publishers.publish_contingency``. This method is not on
        :class:`PlatformPort`.
        """
        kind_u = kind.upper()
        if kind_u == "CLEAR":
            self._subsystem_state = "OPERATE"
            self._faults = (FaultSnapshot(fault_id=self._fault_id),)
            self._readiness = ControlReadiness()
            return
        if kind_u == "MECHANICAL_DAMAGE":
            self._faults = (
                FaultSnapshot(
                    fault_id=uuid4(),
                    fault_code="MECHANICAL_DAMAGE",
                    fault_state="SET",
                    fault_description="Mechanical damage reported",
                ),
            )
            return
        if kind_u == "SENSOR_FAILURE":
            self._subsystem_state = "DEGRADED"
            self._faults = (
                FaultSnapshot(
                    fault_id=uuid4(),
                    fault_code="SENSOR_FAILURE",
                    fault_state="SET",
                    fault_description="Sensor failure reported",
                ),
            )
            return
        if kind_u == "COLLISION_AVOIDANCE":
            self._readiness = ControlReadiness(
                available=False,
                availability="UNAVAILABLE",
                reason="CONSTRAINT_COLLISION_AVOIDANCE",
            )
            return
        raise ValueError(f"Unknown contingency kind: {kind}")

    def apply_system_management(self, *, qnh_kpa: float | None = None) -> str:
        """Store QNH on the TSPI snapshot. Always ``COMPLETED``.

        *qnh_kpa* is converted to hPa (×10).
        """
        if qnh_kpa is None:
            return "COMPLETED"
        # Vehicle Kollsman is hectopascals; QNH request is kilopascals.
        self._vehicle_state = replace(
            self._vehicle_state, kollsman_hpa=float(qnh_kpa) * 10.0
        )
        return "COMPLETED"
