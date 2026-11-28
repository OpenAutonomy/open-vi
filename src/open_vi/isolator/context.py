"""Shared Isolator dependencies."""

from __future__ import annotations

from dataclasses import dataclass, field

from open_vi.asb.port import AsbPort
from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.config import IsolatorConfig
from open_vi.domain import (
    Airfield,
    ControlOffer,
    HomeAirfield,
    redact_control_offer,
)
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
    ``airfield`` is the preloaded home field and TO/L plan ids.
    Isolator serializes writers: inbound and tick do not interleave.
    """

    bus: AsbPort
    platform: PlatformPort
    identity: SystemIdentity
    config: IsolatorConfig
    state: IsolatorState
    routes: RouteStore
    airfield: HomeAirfield
    airfields: tuple[Airfield, ...] = ()
    """The store as loaded, before narrowing to ``airfield``.

    ``airfield`` is the single-runway view the codec builds
    ``AirfieldReport`` from. This is everything the store held:
    further runways, ``Status``, and the optional ``Threshold``.
    Kept so a later consumer -- route vetting needs the runway start
    and status -- reads the same load rather than opening the file a
    second time and risking a different answer.
    """

    flight: FlightSession = field(default_factory=FlightSession)
    execution: RouteExecution = field(default_factory=RouteExecution)

    @property
    def schema_version(self) -> str:
        return self.config.schema_version or SCHEMA_VERSION

    @property
    def message_mode(self) -> str:
        return self.config.message_mode

    def advertised_offer(self) -> ControlOffer:
        """Platform offer intersected with the C2 designation allowlist."""
        return redact_control_offer(
            self.platform.snapshot().offer,
            self.state.c2_capability_types,
        )
