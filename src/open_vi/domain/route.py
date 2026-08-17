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


@dataclass(frozen=True)
class StoredRoutePlan:
    """Route plan bytes retained after MA_RoutePlan ingest."""

    route_plan_id: UUID
    xml: str
    sha256_hex: str
    mission_plan_id: UUID | None = None
    plan_state: str = "READY_FOR_UPLOAD"
