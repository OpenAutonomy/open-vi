"""Isolator-owned A-GRA route ladder and stored plan bytes."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from uuid import UUID

from open_vi.domain import (
    RouteActivationRequest,
    RouteActivationResult,
    StoredRoutePlan,
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


class RouteStore:
    """Ingest / retain MA_RoutePlan bytes and advance the A-GRA route ladder."""

    def __init__(self) -> None:
        self._routes: dict[UUID, _RouteRecord] = {}

    def ingest(
        self,
        route_plan_id: UUID,
        xml: str,
        *,
        mission_plan_id: UUID | None = None,
    ) -> StoredRoutePlan:
        """Retain inbound MA_RoutePlan content for File* / upload."""
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

    def get(self, route_plan_id: UUID) -> StoredRoutePlan | None:
        """Return a previously stored route plan, if any."""
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

    def handle_activation(
        self, req: RouteActivationRequest
    ) -> RouteActivationResult:
        """Advance route lifecycle upload → prepare → activate → deactivate."""
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

    def prime(
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
