"""Isolator session fields with a single owner.

Live activity is :class:`~open_vi.isolator.flight.FlightSession`.
Live route execution is
:class:`~open_vi.isolator.execution.RouteExecution`. Stored plans
are listed from :class:`~open_vi.isolator.routes.RouteStore`.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class IsolatorState:
    """Capability, control assignment, and task — one writer each.

    ``capability_id`` and ``idle_activity_id`` are set at construction.
    ``last_availability`` is written by advertise / contingency.
    Control fields are
    :class:`~open_vi.isolator.handlers.control.ControlHandler`.
    ``active_task_id`` is
    :class:`~open_vi.isolator.handlers.task.TaskHandler`.
    """

    capability_id: uuid.UUID = field(default_factory=uuid.uuid4)
    last_availability: str | None = None
    idle_activity_id: uuid.UUID = field(default_factory=uuid.uuid4)
    controller_system_id: uuid.UUID | None = None
    controller_service_id: uuid.UUID | None = None
    control_type: str | None = None
    active_task_id: uuid.UUID | None = None
