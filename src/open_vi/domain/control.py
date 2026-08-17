"""Control offer and readiness advertised toward MA."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ControlOffer:
    """Control modes the platform is willing to advertise to MA."""

    capability_types: tuple[str, ...] = (
        "HSA_CSA",
        "WAYPOINT_FOLLOWING",
        "CURVE_FOLLOWING",
    )
    capability_label: str = "flight-capability"
    accepted_interfaces: tuple[str, ...] = ("CAPABILITY_COMMAND",)


@dataclass(frozen=True)
class ControlReadiness:
    """Whether MA may currently command the offered flight capability."""

    available: bool = True
    availability: str = "AVAILABLE"
    reason: str | None = None


@dataclass
class PlatformSnapshot:
    """Combined view polled each Isolator tick."""

    offer: ControlOffer = field(default_factory=ControlOffer)
    readiness: ControlReadiness = field(default_factory=ControlReadiness)
