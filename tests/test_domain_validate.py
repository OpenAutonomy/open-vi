"""Pure waypoint-path validator (no MAVLink)."""

from __future__ import annotations

import math

from open_vi.domain import Waypoint, validate_waypoint_path


def test_accepts_in_band_relative_when_home_unknown() -> None:
    result = validate_waypoint_path(
        (Waypoint(10.0, 20.0, 50.0),),
        min_rel_alt_m=10.0,
        max_rel_alt_m=500.0,
        home_hae_m=None,
    )
    assert result is None


def test_accepts_in_band_hae_when_home_known() -> None:
    result = validate_waypoint_path(
        (Waypoint(10.0, 20.0, 500.0),),
        min_rel_alt_m=10.0,
        max_rel_alt_m=500.0,
        home_hae_m=470.0,
    )
    assert result is None


def test_rejects_empty_path() -> None:
    result = validate_waypoint_path(
        (),
        min_rel_alt_m=10.0,
        max_rel_alt_m=500.0,
        home_hae_m=None,
    )
    assert result is not None
    assert result.validation_results == ("INVALID_WAYPOINT",)


def test_rejects_missing_altitude() -> None:
    result = validate_waypoint_path(
        (Waypoint(10.0, 20.0, None),),
        min_rel_alt_m=10.0,
        max_rel_alt_m=500.0,
        home_hae_m=None,
    )
    assert result is not None
    assert result.validation_results == ("INVALID_WAYPOINT",)


def test_rejects_nan_lat() -> None:
    result = validate_waypoint_path(
        (Waypoint(math.nan, 20.0, 50.0),),
        min_rel_alt_m=10.0,
        max_rel_alt_m=500.0,
        home_hae_m=None,
    )
    assert result is not None
    assert result.validation_results == ("INVALID_WAYPOINT",)


def test_rejects_low_relative() -> None:
    result = validate_waypoint_path(
        (Waypoint(10.0, 20.0, 5.0),),
        min_rel_alt_m=10.0,
        max_rel_alt_m=500.0,
        home_hae_m=None,
    )
    assert result is not None
    assert result.validation_results == ("PERFORMANCE_LIMIT_EXCEEDED",)


def test_rejects_high_hae() -> None:
    result = validate_waypoint_path(
        (Waypoint(10.0, 20.0, 2000.0),),
        min_rel_alt_m=10.0,
        max_rel_alt_m=500.0,
        home_hae_m=470.0,
    )
    assert result is not None
    assert result.validation_results == ("PERFORMANCE_LIMIT_EXCEEDED",)
