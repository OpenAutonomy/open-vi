"""Home airfield factory: stable ids and runway extent."""

from __future__ import annotations

import math

import pytest

from open_vi.domain import TspiSnapshot, home_airfield_from_tspi
from open_vi.identity import SystemIdentity


def test_home_airfield_ids_stable_for_identity() -> None:
    identity = SystemIdentity.named("open-vi")
    tspi = TspiSnapshot()
    first = home_airfield_from_tspi(identity, tspi)
    second = home_airfield_from_tspi(identity, tspi)
    assert first.airfield_id == identity.uuid
    assert first.runway_id == second.runway_id
    assert first.takeoff_route_id == second.takeoff_route_id
    assert first.landing_route_id == second.landing_route_id
    assert first.takeoff_route_id != first.landing_route_id


def test_home_airfield_east_runway_length() -> None:
    identity = SystemIdentity.named("open-vi")
    tspi = TspiSnapshot(latitude_deg=38.8895, longitude_deg=-77.0353)
    field = home_airfield_from_tspi(identity, tspi)
    meters_per_deg_lon = 111_320.0 * math.cos(math.radians(38.8895))
    span_deg = (
        field.takeoff_end.longitude_deg - field.takeoff_start.longitude_deg
    )
    assert span_deg * meters_per_deg_lon == pytest.approx(1500.0)
    assert field.landing_start == field.takeoff_end
    assert field.landing_end == field.takeoff_start
