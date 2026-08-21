"""Session state for control authorization and flight activities."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field


@dataclass
class IsolatorState:
    """Mutable Isolator session (capability + active activity)."""

    capability_id: uuid.UUID = field(default_factory=uuid.uuid4)
    advertised: bool = False
    last_availability: str | None = None
    active_activity_id: uuid.UUID | None = None
    idle_activity_id: uuid.UUID = field(default_factory=uuid.uuid4)
    controller_system_id: uuid.UUID | None = None
    controller_service_id: uuid.UUID | None = None
    control_type: str | None = None
    stored_route_ids: list[uuid.UUID] = field(default_factory=list)
    active_route_plan_id: uuid.UUID | None = None
    route_flight_command_id: uuid.UUID | None = None
    route_execution_state: str | None = None
    active_task_id: uuid.UUID | None = None
