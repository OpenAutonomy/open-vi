"""Parse golden MA_FlightCommand (PathSegment / EndPoint / NextPathSegment)."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

from open_vi.codec.command import parse_flight_commands
from open_vi.codec.xmlutil import local_name, parse_xml, tostring

FIXTURES = Path(__file__).parent / "fixtures"

# Degrees matching open-ma DEMO_ROUTE (wire values in the fixture are radians).
GOLDEN_WAYPOINTS = (
    (47.3980, 8.5460, 30.0),
    (47.3985, 8.5465, 30.0),
    (47.3990, 8.5460, 30.0),
)


def _load_golden() -> bytes:
    return (FIXTURES / "MA_FlightCommand.xml").read_bytes()


def _reverse_path_segments(xml: bytes) -> bytes:
    """Put PathSegment children in reverse document order; keep ID links."""
    root = parse_xml(xml)
    for path in (n for n in root.iter() if local_name(n) == "Path"):
        segs = [c for c in list(path) if local_name(c) == "PathSegment"]
        for seg in segs:
            path.remove(seg)
        for seg in reversed(segs):
            path.append(seg)
    return tostring(root)


def _assert_golden_waypoints(cmds) -> None:
    assert len(cmds) == 1
    cmd = cmds[0]
    assert cmd.command_id == UUID(int=0xF1)
    assert cmd.capability_id == UUID(int=0xC0)
    assert cmd.mode == "WAYPOINT_FOLLOWING"
    assert cmd.command_state == "NEW"
    assert len(cmd.waypoints) == len(GOLDEN_WAYPOINTS)
    for got, (lat, lon, alt) in zip(
        cmd.waypoints, GOLDEN_WAYPOINTS, strict=True
    ):
        assert got.latitude_deg == pytest.approx(lat, abs=1e-4)
        assert got.longitude_deg == pytest.approx(lon, abs=1e-4)
        assert got.altitude_m == pytest.approx(alt)


def test_parse_golden_ma_flight_command() -> None:
    xml = _load_golden()
    text = xml.decode()
    assert "MA_FlightCommand" in text
    assert "PathSegment" in text
    assert "NextPathSegment" in text
    assert "EndPoint" in text
    assert "38.8895" not in text
    _assert_golden_waypoints(parse_flight_commands(xml))


def test_parse_follows_next_path_segment_not_document_order() -> None:
    xml = _reverse_path_segments(_load_golden())
    text = xml.decode()
    wp_a = text.find("WP-A")
    wp_c = text.find("WP-C")
    assert wp_c != -1 and wp_a != -1
    assert wp_c < wp_a
    _assert_golden_waypoints(parse_flight_commands(xml))
