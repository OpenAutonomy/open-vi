"""AirfieldReport runway geometry."""

from __future__ import annotations

from open_vi.codec.query import build_airfield_report
from open_vi.domain import TspiSnapshot, home_airfield_from_tspi
from open_vi.identity import SystemIdentity


def test_airfield_report_includes_runway_geometry() -> None:
    identity = SystemIdentity.named("open-vi")
    field = home_airfield_from_tspi(identity, TspiSnapshot())
    raw = build_airfield_report(identity, airfield=field)
    body = raw.decode() if isinstance(raw, bytes) else raw
    assert "AirfieldReport" in body
    assert "Runway" in body
    assert "TakeoffCoordinates" in body
    assert "LandingCoordinates" in body
    assert "AvailableLength" in body
    assert field.runway_id.hex in body.replace("-", "")
    assert field.airfield_id.hex in body.replace("-", "")
    assert "Start" in body
    assert "Limit" in body
