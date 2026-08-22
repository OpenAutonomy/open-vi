"""Control offer and readiness advertised toward MA."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AirspeedLimit:
    """One airspeed sample at an altitude (optional weight)."""

    speed_mps: float
    altitude_m: float
    # SpeedReferenceEnum
    speed_ref: str = "TRUE_AIRSPEED"
    # AltitudeReferenceEnum
    altitude_ref: str = "AGL"
    weight_kg: float | None = None


@dataclass(frozen=True)
class AccelerationLimit:
    """Body acceleration paired with Mach or body rates.

    UCI requires ``AccelerationLimitPair`` as a choice: ``mach`` or
    all three rates. Open-VI does not invent the pair.
    """

    x_mps2: float
    y_mps2: float
    z_mps2: float
    mach: float | None = None
    roll_rate_rps: float | None = None
    pitch_rate_rps: float | None = None
    yaw_rate_rps: float | None = None


@dataclass(frozen=True)
class FlightModeProfile:
    """Performance envelope for one advertised flight control mode."""

    min_altitude_m: float | None = None
    max_altitude_m: float | None = None
    # AltitudeReferenceEnum: WGS_HAE | AGL | MSL | ALTITUDE_BAROMETRIC
    altitude_ref: str = "AGL"
    min_airspeed: tuple[AirspeedLimit, ...] = ()
    max_airspeed: tuple[AirspeedLimit, ...] = ()
    best_endurance_airspeed: tuple[AirspeedLimit, ...] = ()
    best_range_airspeed: tuple[AirspeedLimit, ...] = ()
    min_acceleration: tuple[AccelerationLimit, ...] = ()
    max_acceleration: tuple[AccelerationLimit, ...] = ()
    max_turn_rate_rps: float | None = None
    max_climb_rate_mps: float | None = None
    max_descent_rate_mps: float | None = None


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
    waypoint_profile: FlightModeProfile | None = None
    hsa_profile: FlightModeProfile | None = None
    curve_profile: FlightModeProfile | None = None


def redact_control_offer(
    offer: ControlOffer, allowed: tuple[str, ...] | None
) -> ControlOffer:
    """Intersect *offer* with a C2 designation allowlist.

    ``None`` means no overlay (advertise the platform offer). An empty
    tuple means C2 permitted no modes.
    """
    if allowed is None:
        return offer
    permitted = frozenset(allowed)
    types = tuple(mode for mode in offer.capability_types if mode in permitted)
    return ControlOffer(
        capability_types=types,
        capability_label=offer.capability_label,
        accepted_interfaces=offer.accepted_interfaces,
        waypoint_profile=(
            offer.waypoint_profile if "WAYPOINT_FOLLOWING" in types else None
        ),
        hsa_profile=offer.hsa_profile if "HSA_CSA" in types else None,
        curve_profile=(
            offer.curve_profile if "CURVE_FOLLOWING" in types else None
        ),
    )


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
