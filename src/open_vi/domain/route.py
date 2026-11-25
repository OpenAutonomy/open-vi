"""Internal route activation and stored-plan types (not UCI)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID


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
    awaiting_vehicle: bool = False


@dataclass(frozen=True)
class StoredRoutePlan:
    """Route plan bytes retained after MA_RoutePlan ingest."""

    route_plan_id: UUID
    xml: str
    sha256_hex: str
    mission_plan_id: UUID | None = None
    plan_state: str = "READY_FOR_UPLOAD"


@dataclass(frozen=True)
class RouteProgress:
    """Position along the waypoint list as submitted to the backend.

    ``waypoint_index`` is 0-based into the tuple the Isolator passed to
    ``submit_flight_command``, not into whatever the backend actually
    uploaded. A backend that trims or reorders waypoints owns the
    mapping back — PX4 drops a leading prefix, so its mission item
    sequence is not this index.

    ``captured`` distinguishes "heading for this waypoint" from
    "reached it". A-GRA's PreviousSegment carries a mandatory
    ActualCaptureTime, so a segment can only be reported as previous
    once it has actually been captured.
    """

    waypoint_index: int
    total_waypoints: int
    captured: bool = False


@dataclass(frozen=True)
class PlanExecutionSnapshot:
    """Live route/mission execution for Isolator outs (not UCI)."""

    execution_state: str  # EXECUTING | COMPLETED | FAILED
    route_plan_id: UUID
    mission_plan_id: UUID | None = None
    activity_id: UUID | None = None
    source: str = "ACTUAL"
    progress: RouteProgress | None = None
