"""Isolator: TSPI / vehicle-state outs."""

from __future__ import annotations

import math

from open_vi.asb import InMemoryAsb
from open_vi.codec.xmlutil import local_name, parse_xml
from open_vi.config import IsolatorConfig
from open_vi.isolator import Isolator
from open_vi.isolator.executive import (
    MT_COMPONENT_STATUS,
    MT_NAVIGATION_REPORT,
    MT_POSITION_REPORT_DETAILED,
    MT_WEATHER_OBSERVATION,
)
from open_vi.isolator.handlers.flight_command import MT_FLIGHT_ACTIVITY
from open_vi.platform import StubPlatform


def test_vehicle_state_publishes_five_roots_in_order() -> None:
    bus = InMemoryAsb()
    bus.connect()
    seen: list[str] = []
    bus.on_message(lambda mt, _xml: seen.append(mt))

    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(
            tick_republish_status=False,
            publish_vehicle_state=True,
        ),
    )
    iso.publish_vehicle_state_once()

    assert seen[:5] == [
        MT_FLIGHT_ACTIVITY,
        MT_POSITION_REPORT_DETAILED,
        MT_WEATHER_OBSERVATION,
        MT_NAVIGATION_REPORT,
        MT_COMPONENT_STATUS,
    ]


def test_position_report_detailed_uses_radians_and_ned() -> None:
    bus = InMemoryAsb()
    bus.connect()
    iso = Isolator(bus, platform=StubPlatform())
    iso.publish_vehicle_state_once()

    raw = bus.published[MT_POSITION_REPORT_DETAILED][-1]
    root = parse_xml(raw)
    assert local_name(root) == "MA_PositionReportDetailed"
    assert "AbsolutePoint" in raw
    assert "NorthSpeed" in raw
    assert "PositionPositionCovariance" in raw
    assert "AirData" in raw
    assert "Orientation" in raw
    assert "MagneticHeading" in raw
    # Stub home lat ~38.8895 deg → radians present as ~0.678...
    expected = math.radians(38.8895)
    assert f"{expected:.5f}"[:6] in raw or f"{expected:.9g}" in raw


def test_navigation_and_weather_and_component() -> None:
    bus = InMemoryAsb()
    bus.connect()
    iso = Isolator(bus, platform=StubPlatform())
    iso.publish_vehicle_state_once()

    nav = bus.published[MT_NAVIGATION_REPORT][-1]
    assert local_name(parse_xml(nav)) == "NavigationReport"
    assert "ACTUAL" in nav
    assert "NORMAL" in nav
    assert "Percent" in nav

    weather = bus.published[MT_WEATHER_OBSERVATION][-1]
    assert local_name(parse_xml(weather)) == "WeatherObservation"
    assert "OTHER" in weather
    assert "WindVelocity" in weather
    assert "ObservationPoint" in weather

    component = bus.published[MT_COMPONENT_STATUS][-1]
    assert local_name(parse_xml(component)) == "ComponentStatus"
    assert "OPERATIONAL" in component
    assert "engine" in component


def test_idle_activity_when_no_command() -> None:
    bus = InMemoryAsb()
    bus.connect()
    iso = Isolator(bus, platform=StubPlatform())
    iso.publish_vehicle_state_once()
    activity = bus.published[MT_FLIGHT_ACTIVITY][-1]
    assert "ENABLED" in activity
    assert "VehicleCommandState" in activity
