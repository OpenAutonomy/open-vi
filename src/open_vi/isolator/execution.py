"""Live route execution owned by Isolator.

:class:`RouteExecution` is EXECUTING / COMPLETED / FAILED for the
active plan. The A-GRA ladder (upload → prepare → activate) stays
on :class:`~open_vi.isolator.routes.RouteStore`. Publishers only
read these fields.
"""

from __future__ import annotations

from uuid import UUID


class RouteExecution:
    """One live route: plan id, route-sourced command id, and state.

    :meth:`activate` starts EXECUTING. The tick calls :meth:`complete`
    when the platform finishes that command. DEACTIVATE calls
    :meth:`mark_failed` so publishers can emit FAILED, then
    :meth:`clear`.
    """

    def __init__(self) -> None:
        self.plan_id: UUID | None = None
        self.command_id: UUID | None = None
        self.state: str | None = None

    def activate(self, plan_id: UUID, command_id: UUID) -> None:
        """Start EXECUTING for *plan_id* under route-sourced *command_id*."""
        self.plan_id = plan_id
        self.command_id = command_id
        self.state = "EXECUTING"

    def complete(self) -> None:
        """Mark COMPLETED. Keep ids so the status package can republish."""
        self.state = "COMPLETED"

    def mark_failed(self) -> None:
        """Mark FAILED. Keep ids so publishers can emit, then :meth:`clear`."""
        self.state = "FAILED"

    def clear(self) -> None:
        """Drop the live route. No plan-execution snapshot after this."""
        self.plan_id = None
        self.command_id = None
        self.state = None

    def is_sourced(self, command_id: UUID) -> bool:
        """True when *command_id* is the live route-sourced command."""
        return self.command_id is not None and command_id == self.command_id
