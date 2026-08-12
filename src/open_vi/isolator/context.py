"""Shared Isolator dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from open_vi.asb.port import AsbPort
from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.config import IsolatorConfig
from open_vi.identity import SystemIdentity
from open_vi.isolator.state import IsolatorState
from open_vi.platform.port import PlatformPort


@dataclass
class IsolatorContext:
    """Handle passed to tick logic and (later) inbound handlers."""

    bus: AsbPort
    platform: PlatformPort
    identity: SystemIdentity
    config: IsolatorConfig
    state: IsolatorState

    @property
    def schema_version(self) -> str:
        return self.config.schema_version or SCHEMA_VERSION

    @property
    def message_mode(self) -> str:
        return self.config.message_mode
