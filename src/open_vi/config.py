"""Runtime configuration for ASB and Isolator."""

from __future__ import annotations

import os
from dataclasses import dataclass

from open_vi.identity import (
    DEFAULT_NAMESPACE_NAME,
    DEFAULT_NAMESPACE_UUID,
    DEFAULT_SYSTEM_NAME,
)


@dataclass(frozen=True)
class AsbConfig:
    """Connection settings for the Abstract Service Bus (ActiveMQ STOMP)."""

    host: str = "localhost"
    stomp_port: int = 61613
    username: str | None = None
    password: str | None = None
    heartbeat_ms: int = 0

    @classmethod
    def from_env(cls) -> AsbConfig:
        user = os.environ.get(
            "ASB_USERNAME", os.environ.get("ACTIVEMQ_USER") or None
        )
        password = os.environ.get(
            "ASB_PASSWORD", os.environ.get("ACTIVEMQ_PASSWORD") or None
        )
        if os.environ.get("ASB_ANONYMOUS", "").lower() in {"1", "true", "yes"}:
            user = None
            password = None
        return cls(
            host=os.environ.get("BROKER_HOST", "localhost"),
            stomp_port=int(os.environ.get("STOMP_PORT", "61613")),
            username=user,
            password=password,
            heartbeat_ms=int(os.environ.get("ASB_HEARTBEAT_MS", "0")),
        )


@dataclass(frozen=True)
class IsolatorConfig:
    """Isolator identity, timing, and compliance knobs."""

    asb: AsbConfig | None = None
    system_name: str = DEFAULT_SYSTEM_NAME
    system_label: str = DEFAULT_SYSTEM_NAME
    namespace_name: str = DEFAULT_NAMESPACE_NAME
    namespace_uuid: str = str(DEFAULT_NAMESPACE_UUID)
    schema_version: str = "005.0a"
    message_mode: str = "SIMULATION"
    compliance_mode: str = "loose"
    tick_period_s: float = 5.0
    tick_republish_status: bool = True
    publish_vehicle_state: bool = True
    publish_status_package: bool = True

    @classmethod
    def from_env(cls) -> IsolatorConfig:
        system_name = os.environ.get("VI_SYSTEM_NAME", DEFAULT_SYSTEM_NAME)
        return cls(
            asb=AsbConfig.from_env(),
            system_name=system_name,
            system_label=os.environ.get("VI_SYSTEM_LABEL", system_name),
            namespace_name=os.environ.get(
                "VI_NAMESPACE_NAME", DEFAULT_NAMESPACE_NAME
            ),
            namespace_uuid=os.environ.get(
                "VI_NAMESPACE_UUID",
                str(DEFAULT_NAMESPACE_UUID),
            ),
            schema_version=os.environ.get("AGRA_SCHEMA_VERSION", "005.0a"),
            message_mode=os.environ.get("AGRA_MESSAGE_MODE", "SIMULATION"),
            compliance_mode=os.environ.get("COMPLIANCE_MODE", "loose").lower(),
            tick_period_s=float(os.environ.get("VI_TICK_PERIOD_S", "5")),
            tick_republish_status=os.environ.get(
                "VI_TICK_REPUBLISH_STATUS", "true"
            ).lower()
            in {"1", "true", "yes"},
            publish_vehicle_state=os.environ.get(
                "VI_PUBLISH_VEHICLE_STATE", "true"
            ).lower()
            in {"1", "true", "yes"},
            publish_status_package=os.environ.get(
                "VI_PUBLISH_STATUS_PACKAGE", "true"
            ).lower()
            in {"1", "true", "yes"},
        )
