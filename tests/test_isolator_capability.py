"""Isolator: control-mode authorization advertise path."""

from __future__ import annotations

from open_vi.asb import InMemoryAsb
from open_vi.codec.xmlutil import local_name, parse_xml
from open_vi.config import IsolatorConfig
from open_vi.domain import ControlOffer, ControlReadiness, FlightModeProfile
from open_vi.isolator import Isolator
from open_vi.isolator.publishers import (
    MT_FLIGHT_CAPABILITY,
    MT_FLIGHT_CAPABILITY_STATUS,
)
from open_vi.platform import StubPlatform


def test_advertise_publishes_capability_then_status() -> None:
    bus = InMemoryAsb()
    bus.connect()
    seen: list[str] = []
    bus.on_message(lambda mt, _xml: seen.append(mt))

    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(tick_republish_status=False),
    )
    iso.advertise_once()

    assert seen[:2] == [
        MT_FLIGHT_CAPABILITY,
        MT_FLIGHT_CAPABILITY_STATUS,
    ]
    assert iso.ctx.state.last_availability == "AVAILABLE"


def test_capability_xml_contains_control_modes() -> None:
    bus = InMemoryAsb()
    bus.connect()
    iso = Isolator(bus, platform=StubPlatform())
    iso.advertise_once()

    raw = bus.wait_for(MT_FLIGHT_CAPABILITY, timeout=0.5)
    assert raw is not None
    root = parse_xml(raw)
    assert local_name(root) == "MA_FlightCapability"
    assert "HSA_CSA" in raw
    assert "WAYPOINT_FOLLOWING" in raw
    assert "CURVE_FOLLOWING" in raw
    assert "CAPABILITY_COMMAND" in raw
    assert "WaypointFollowingPerformanceProfile" not in raw


def test_advertise_includes_waypoint_profile() -> None:
    bus = InMemoryAsb()
    bus.connect()
    iso = Isolator(
        bus,
        platform=StubPlatform(
            offer=ControlOffer(
                waypoint_profile=FlightModeProfile(
                    min_altitude_m=10.0,
                    max_altitude_m=500.0,
                    altitude_ref="AGL",
                )
            )
        ),
    )
    iso.advertise_once()
    raw = bus.wait_for(MT_FLIGHT_CAPABILITY, timeout=0.5)
    assert raw is not None
    assert "WaypointFollowingPerformanceProfile" in raw
    assert "MinAltitude" in raw
    assert "AGL" in raw


def test_status_xml_available() -> None:
    bus = InMemoryAsb()
    bus.connect()
    iso = Isolator(bus, platform=StubPlatform())
    iso.advertise_once()

    # Second published message type queue — wait_for returns first of that MT.
    status = bus.published[MT_FLIGHT_CAPABILITY_STATUS][0]
    root = parse_xml(status)
    assert local_name(root) == "MA_FlightCapabilityStatus"
    body = status if isinstance(status, str) else status.decode()
    assert "AVAILABLE" in body


def test_readiness_change_readvertises() -> None:
    bus = InMemoryAsb()
    bus.connect()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(tick_period_s=0.05, tick_republish_status=False),
    )
    iso.advertise_once()
    before = len(bus.published[MT_FLIGHT_CAPABILITY])

    platform.set_readiness(
        ControlReadiness(
            available=False,
            availability="TEMPORARILY_UNAVAILABLE",
            reason="CONSTRAINT_COLLISION_AVOIDANCE",
        )
    )
    iso._tick()  # pylint: disable=protected-access

    assert len(bus.published[MT_FLIGHT_CAPABILITY]) == before + 1
    assert iso.ctx.state.last_availability == "TEMPORARILY_UNAVAILABLE"
