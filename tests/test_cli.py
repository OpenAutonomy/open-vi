"""CLI first-hour: --memory --once prints MA_FlightCapability."""

from __future__ import annotations

from open_vi.__main__ import main


def test_memory_once_prints_flight_capability(capsys) -> None:
    assert main(["--memory", "--once"]) == 0
    out = capsys.readouterr().out
    assert "MA_FlightCapability" in out
    assert "WAYPOINT_FOLLOWING" in out
