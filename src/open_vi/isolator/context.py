"""Shared Isolator dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field

from open_vi.asb.port import AsbPort
from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.config import IsolatorConfig
from open_vi.identity import SystemIdentity
from open_vi.isolator.execution import RouteExecution
from open_vi.isolator.flight import FlightSession
from open_vi.isolator.routes import RouteStore
from open_vi.isolator.state import IsolatorState
from open_vi.platform.port import PlatformPort


@dataclass
class IsolatorContext:
    """Handle passed to handlers and the tick.

    ``state`` holds single-owner fields. ``flight`` and ``execution``
    own the live activity and route. ``routes`` is the plan ladder.
    """

    bus: AsbPort
    platform: PlatformPort
    identity: SystemIdentity
    config: IsolatorConfig
    state: IsolatorState
    routes: RouteStore
    flight: FlightSession = field(default_factory=FlightSession)
    execution: RouteExecution = field(default_factory=RouteExecution)

    @property
    def schema_version(self) -> str:
        return self.config.schema_version or SCHEMA_VERSION

    @property
    def message_mode(self) -> str:
        return self.config.message_mode
