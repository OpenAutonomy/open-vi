"""Inbound Isolator handlers."""

from __future__ import annotations

import logging
from collections.abc import Sequence

from open_vi.isolator.handlers.base import MessageHandler
from open_vi.isolator.handlers.control import ControlHandler
from open_vi.isolator.handlers.failsafe import FailsafeHandler
from open_vi.isolator.handlers.flight_command import FlightCommandHandler
from open_vi.isolator.handlers.heartbeat import HeartbeatHandler
from open_vi.isolator.handlers.query import QueryHandler
from open_vi.isolator.handlers.route import RouteHandler
from open_vi.isolator.handlers.system_mgmt import SystemManagementHandler
from open_vi.isolator.handlers.task import TaskHandler

LOGGER = logging.getLogger(__name__)

__all__ = [
    "ControlHandler",
    "FailsafeHandler",
    "FlightCommandHandler",
    "HeartbeatHandler",
    "MessageHandler",
    "QueryHandler",
    "RouteHandler",
    "SystemManagementHandler",
    "TaskHandler",
    "collect_inbound_mts",
    "default_handlers",
]


def default_handlers() -> list[MessageHandler]:
    """Default inbound handler set for Isolator construction."""
    return [
        FlightCommandHandler(),
        HeartbeatHandler(),
        RouteHandler(),
        FailsafeHandler(),
        SystemManagementHandler(),
        QueryHandler(),
        ControlHandler(),
        TaskHandler(),
    ]


def collect_inbound_mts(handlers: Sequence[MessageHandler]) -> tuple[str, ...]:
    """Unique inbound MT names declared on handlers (order preserved)."""
    seen: list[str] = []
    for handler in handlers:
        mts = getattr(handler, "inbound_mts", None)
        if not mts:
            LOGGER.warning(
                "handler %s missing inbound_mts; will not be subscribed",
                type(handler).__name__,
            )
            continue
        for mt in mts:
            if mt not in seen:
                seen.append(mt)
    return tuple(seen)
