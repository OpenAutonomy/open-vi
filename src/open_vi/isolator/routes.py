"""Isolator-owned route ladder and retained ``MA_RoutePlan`` bytes.

:class:`RouteStore` sits next to
:class:`~open_vi.isolator.execution.RouteExecution`.
Route and query handlers read and write it; they do not ask
:class:`~open_vi.platform.port.PlatformPort`.
``ACTIVATE`` and ``DEACTIVATE`` from ``ACTIVATED`` return
``awaiting_vehicle`` so the handler can submit or cancel on the
port, then :meth:`commit`. This module does not parse waypoints.

The store jumps to the terminal plan state for upload/prepare
steps. Mid-states (``PREPARING_FOR_UPLOAD``, ``UPLOADING``, …)
live on :class:`RouteActivationResult` so the handler can walk
the status ladder. ``prime`` is a test helper.
"""

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
# emit_pair False → handler publishes a single status (DEACTIVATE).
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
    """One plan: optional XML, sha256, and current PlanActivation state."""

    route_plan_id: UUID
    mission_plan_id: UUID | None = None
    state: str = "INACTIVE"
    xml: str | None = None
    sha256_hex: str | None = None


class RouteStore:
    """Retain plan bytes and accept or reject ladder commands.

    Ladder: ``PREPARE_FOR_UPLOAD`` → ``UPLOAD`` →
    ``PREPARE_FOR_ACTIVATION`` → ``ACTIVATE``, or ``DEACTIVATE`` from
    ``READY_FOR_ACTIVATION`` / ``ACTIVATED``. Unknown commands and
    illegal from-states are ``REJECTED``. ``UPLOAD`` and ``ACTIVATE``
    also reject when no XML has been ingested. ``ACTIVATE`` and
    ``DEACTIVATE`` from ``ACTIVATED`` do not set the terminal state
    until the handler :meth:`commit`.
    """

    def __init__(self) -> None:
        self._routes: dict[UUID, _RouteRecord] = {}

    def ingest(
        self,
        route_plan_id: UUID,
        xml: str,
        *,
        mission_plan_id: UUID | None = None,
    ) -> StoredRoutePlan:
        """Store inbound ``MA_RoutePlan`` XML and its sha256.

        Does not publish File* — the route handler does that on first
        ingest. A plan in ``INACTIVE`` or ``DEACTIVATED`` (or a new
        id) moves to ``READY_FOR_UPLOAD`` so ``UPLOAD`` can proceed.
        """
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

    def ingested_ids(self) -> tuple[UUID, ...]:
        """Ids of plans that have XML, in ingest order.

        Same rule as :meth:`get`: a PREPARE-only record (no XML) is
        omitted. Query walks this instead of a second Isolator list.
        """
        return tuple(
            route_id
            for route_id, record in self._routes.items()
            if record.xml is not None and record.sha256_hex is not None
        )

    def get(self, route_plan_id: UUID) -> StoredRoutePlan | None:
        """Return a plan that has XML and a digest, or ``None``.

        A record created only by ``PREPARE_FOR_UPLOAD`` (no ingest)
        is not returned here.
        """
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
        """Accept or reject one activation command.

        Mid-state and ``emit_pair`` go on the result for the handler.
        ``DEACTIVATE`` from ready sets ``emit_pair`` false so the
        handler publishes a single status. ``ACTIVATE`` and
        ``DEACTIVATE`` from ``ACTIVATED`` set ``awaiting_vehicle``
        and do not change plan state — the handler
        :meth:`commit` after the platform accepts. ``PREPARE_FOR_UPLOAD``
        may create a record with no XML; ``UPLOAD`` and ``ACTIVATE``
        require a prior :meth:`ingest`.
        """
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
        if req.command_type in {"UPLOAD", "ACTIVATE"} and (
            record is None or record.xml is None
        ):
            return RouteActivationResult(
                processing_state="REJECTED",
                plan_state=current or "INACTIVE",
                emit_pair=False,
                reason="INVALID_INPUT_PARAMETER",
                reason_description=(
                    f"No stored MA_RoutePlan for {req.command_type}"
                ),
            )
        if record is None:
            record = _RouteRecord(
                route_plan_id=req.route_plan_id,
                mission_plan_id=req.mission_plan_id,
            )
            self._routes[req.route_plan_id] = record
        record.mission_plan_id = req.mission_plan_id
        if req.command_type == "ACTIVATE":
            return RouteActivationResult(
                processing_state="ACCEPTED",
                plan_state=record.state,
                progress_state=mid,
                emit_pair=True,
                awaiting_vehicle=True,
            )
        if req.command_type == "DEACTIVATE" and record.state == "ACTIVATED":
            return RouteActivationResult(
                processing_state="ACCEPTED",
                plan_state=record.state,
                emit_pair=False,
                awaiting_vehicle=True,
            )
        record.state = terminal
        return RouteActivationResult(
            processing_state="ACCEPTED",
            plan_state=terminal,
            progress_state=mid,
            emit_pair=emit_pair,
        )

    def commit(self, route_plan_id: UUID, terminal: str) -> None:
        """Set the terminal plan state after the handler finishes I/O.

        Used for ``ACTIVATE`` (after the platform accepts) and
        ``DEACTIVATE`` from ``ACTIVATED`` (after cancel). Unknown ids
        are ignored.
        """
        record = self._routes.get(route_plan_id)
        if record is None:
            return
        record.state = terminal

    def prime(
        self,
        route_plan_id: UUID,
        *,
        mission_plan_id: UUID | None = None,
        state: str = "READY_FOR_ACTIVATION",
        xml: str | None = None,
    ) -> None:
        """Test helper: place a route into a lifecycle state.

        Optional *xml* is hashed the same way as :meth:`ingest`.
        """
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
