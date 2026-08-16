"""Deterministic platform backend for harness-first Isolator development."""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, replace
from uuid import UUID, uuid4

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
)

_ACCEPTED_MODES = frozenset(
    {"WAYPOINT_FOLLOWING", "HSA_CSA", "CURVE_FOLLOWING"}
)

# command_type → (allowed from-states, mid-state, terminal-state, emit_pair)
_ROUTE_TRANSITIONS: dict[
    str, tuple[frozenset[str | None], str | None, str, bool]
] = {
    "PREPARE_FOR_UPLOAD": (
        frozenset({None, "INACTIVE", "DEACTIVATED", "READY_FOR_UPLOAD"}),
        "PREPARING_FOR_UPLOAD",
        "READY_FOR_UPLOAD",
        True,
    ),
    "UPLOAD": (
        frozenset({"READY_FOR_UPLOAD"}),
        "UPLOADING",
        "UPLOADED",
        True,
    ),
    "PREPARE_FOR_ACTIVATION": (
        frozenset({"UPLOADED"}),
        "PREPARING_FOR_ACTIVATION",
        "READY_FOR_ACTIVATION",
        True,
    ),
    "ACTIVATE": (
        frozenset({"READY_FOR_ACTIVATION"}),
        "ACTIVATING",
        "ACTIVATED",
        True,
    ),
    "DEACTIVATE": (
        frozenset({"READY_FOR_ACTIVATION", "ACTIVATED"}),
        None,
        "DEACTIVATED",
        False,
    ),
}


@dataclass
class _RouteRecord:
    route_plan_id: UUID
    mission_plan_id: UUID | None = None
    state: str = "INACTIVE"
    xml: str | None = None
    sha256_hex: str | None = None


class StubPlatform(PlatformPort):
    """Fixed control offer + TSPI + status; accepts all three A-GRA modes."""

    def __init__(
        self,
        *,
        offer: ControlOffer | None = None,
        readiness: ControlReadiness | None = None,
        vehicle_state: TsipSnapshot | None = None,
        service_id: UUID | None = None,
        subsystem_id: UUID | None = None,
    ) -> None:
        self._offer = offer or ControlOffer()
        self._readiness = readiness or ControlReadiness()
        self._activity: FlightActivitySnapshot | None = None
        self._commands: dict[UUID, str] = {}
        self._pending_updates: list[tuple[UUID, CommandResult]] = []
        self._routes: dict[UUID, _RouteRecord] = {}
        self._vehicle_state = vehicle_state or TsipSnapshot(
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
        return PlatformSnapshot(offer=self._offer, readiness=self._readiness)

    def set_readiness(self, readiness: ControlReadiness) -> None:
        """Test helper: change availability without rebuilding the Isolator."""
        self._readiness = readiness

    def submit_flight_command(self, cmd: FlightCommandRequest) -> CommandResult:
        if not self._readiness.available:
            return CommandResult(
                processing_state="REJECTED",
                reason="CAPABILITY_UNAVAILABLE",
                reason_description="Flight capability not available",
            )
        if cmd.choice != "Capability":
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description="Activity modify not supported yet",
            )
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

    def complete_flight_command(
        self, command_id: UUID | None = None
    ) -> UUID | None:
        """Mark the live command COMPLETED for the next Isolator poll."""
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
            self._activity = replace(
                self._activity, activity_state="COMPLETED"
            )
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
        updates = list(self._pending_updates)
        self._pending_updates.clear()
        return updates

    def active_flight_activity(self) -> FlightActivitySnapshot | None:
        return self._activity

    def get_vehicle_state(self) -> TsipSnapshot:
        return self._vehicle_state

    def get_service_status(self) -> ServiceStatusSnapshot:
        secs = max(0, int(time.monotonic() - self._started))
        return ServiceStatusSnapshot(
            service_id=self._service_id,
            time_up=f"PT{secs}S",
        )

    def get_subsystem_status(self) -> SubsystemStatusSnapshot:
        return SubsystemStatusSnapshot(
            subsystem_id=self._subsystem_id,
            subsystem_state=self._subsystem_state,
        )

    def get_faults(self) -> tuple[FaultSnapshot, ...]:
        return self._faults

    def inject_contingency(self, kind: str) -> None:
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
        if qnh_kpa is None:
            return "COMPLETED"
        # Vehicle Kollsman is hectopascals; QNH request is kilopascals.
        self._vehicle_state = replace(
            self._vehicle_state, kollsman_hpa=float(qnh_kpa) * 10.0
        )
        return "COMPLETED"

    def prime_route(
        self,
        route_plan_id: UUID,
        *,
        mission_plan_id: UUID | None = None,
        state: str = "READY_FOR_ACTIVATION",
        xml: str | None = None,
    ) -> None:
        """Test helper: place a route into a lifecycle state."""
        digest = None
        if xml is not None:
            digest = hashlib.sha256(xml.encode("utf-8")).hexdigest()
        self._routes[route_plan_id] = _RouteRecord(
            route_plan_id=route_plan_id,
            mission_plan_id=mission_plan_id,
            state=state,
            xml=xml,
            sha256_hex=digest,
        )

    def handle_route_activation(
        self, req: RouteActivationRequest
    ) -> RouteActivationResult:
        transition = _ROUTE_TRANSITIONS.get(req.command_type)
        if transition is None:
            return RouteActivationResult(
                processing_state="REJECTED",
                plan_state="INACTIVE",
                emit_pair=False,
                reason="INVALID_INPUT_PARAMETER",
                reason_description=(
                    f"Unsupported CommandType {req.command_type}"
                ),
            )
        allowed, mid, terminal, emit_pair = transition
        record = self._routes.get(req.route_plan_id)
        current = record.state if record is not None else None
        if current not in allowed:
            return RouteActivationResult(
                processing_state="REJECTED",
                plan_state=current or "INACTIVE",
                emit_pair=False,
                reason="INVALID_INPUT_PARAMETER",
                reason_description=(
                    f"Cannot {req.command_type} from state {current}"
                ),
            )
        if req.command_type == "UPLOAD" and (
            record is None or record.xml is None
        ):
            return RouteActivationResult(
                processing_state="REJECTED",
                plan_state=current or "INACTIVE",
                emit_pair=False,
                reason="INVALID_INPUT_PARAMETER",
                reason_description="No stored MA_RoutePlan for UPLOAD",
            )
        if record is None:
            record = _RouteRecord(
                route_plan_id=req.route_plan_id,
                mission_plan_id=req.mission_plan_id,
            )
            self._routes[req.route_plan_id] = record
        record.mission_plan_id = req.mission_plan_id
        record.state = terminal
        return RouteActivationResult(
            processing_state="ACCEPTED",
            plan_state=terminal,
            progress_state=mid,
            emit_pair=emit_pair,
        )

    def store_route_plan(
        self,
        route_plan_id: UUID,
        xml: str,
        *,
        mission_plan_id: UUID | None = None,
    ) -> StoredRoutePlan:
        digest = hashlib.sha256(xml.encode("utf-8")).hexdigest()
        record = self._routes.get(route_plan_id)
        if record is None:
            record = _RouteRecord(route_plan_id=route_plan_id)
            self._routes[route_plan_id] = record
        if mission_plan_id is not None:
            record.mission_plan_id = mission_plan_id
        record.xml = xml
        record.sha256_hex = digest
        if record.state in (None, "INACTIVE", "DEACTIVATED"):
            record.state = "READY_FOR_UPLOAD"
        return StoredRoutePlan(
            route_plan_id=route_plan_id,
            xml=xml,
            sha256_hex=digest,
            mission_plan_id=record.mission_plan_id,
            plan_state=record.state,
        )

    def get_stored_route(self, route_plan_id: UUID) -> StoredRoutePlan | None:
        record = self._routes.get(route_plan_id)
        if record is None or record.xml is None or record.sha256_hex is None:
            return None
        return StoredRoutePlan(
            route_plan_id=record.route_plan_id,
            xml=record.xml,
            sha256_hex=record.sha256_hex,
            mission_plan_id=record.mission_plan_id,
            plan_state=record.state,
        )
