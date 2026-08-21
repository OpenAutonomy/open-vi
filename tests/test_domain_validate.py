"""Pure waypoint-path and HSA validators (no MAVLink)."""

from __future__ import annotations

import math

from open_vi.domain import (
    HsaCsaSetpoint,
    Waypoint,
    finite_waypoint_geometry,
    validate_hsa_setpoint,
    validate_waypoint_path,
)


def test_finite_geometry_rejects_empty_and_nan() -> None:
    assert finite_waypoint_geometry((Waypoint(10.0, 20.0, 50.0),))
    assert not finite_waypoint_geometry(())
    assert not finite_waypoint_geometry((Waypoint(10.0, 20.0, None),))
    assert not finite_waypoint_geometry((Waypoint(math.nan, 20.0, 50.0),))


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


def test_hsa_empty_is_hold_current() -> None:
    assert (
        validate_hsa_setpoint(
            HsaCsaSetpoint(),
            min_rel_alt_m=10.0,
            max_rel_alt_m=500.0,
            home_hae_m=None,
        )
        is None
    )
    assert (
        validate_hsa_setpoint(
            None,
            min_rel_alt_m=10.0,
            max_rel_alt_m=500.0,
            home_hae_m=None,
        )
        is None
    )


def test_hsa_accepts_agl_in_band() -> None:
    result = validate_hsa_setpoint(
        HsaCsaSetpoint(
            altitude_m=50.0,
            altitude_ref="AGL",
            speed_mps=5.0,
            speed_ref="GROUNDSPEED",
            heading_deg=90.0,
            heading_ref="TRUE_NORTH",
        ),
        min_rel_alt_m=10.0,
        max_rel_alt_m=500.0,
        home_hae_m=None,
    )
    assert result is None


def test_hsa_rejects_mach() -> None:
    result = validate_hsa_setpoint(
        HsaCsaSetpoint(unsupported="MACH"),
        min_rel_alt_m=10.0,
        max_rel_alt_m=500.0,
        home_hae_m=None,
    )
    assert result is not None
    assert result.validation_results == ("CAPABILITY_NOT_SUPPORTED",)


def test_hsa_rejects_tas() -> None:
    result = validate_hsa_setpoint(
        HsaCsaSetpoint(speed_mps=10.0, speed_ref="TRUE_AIRSPEED"),
        min_rel_alt_m=10.0,
        max_rel_alt_m=500.0,
        home_hae_m=None,
    )
    assert result is not None
    assert result.validation_results == ("CAPABILITY_NOT_SUPPORTED",)


def test_hsa_rejects_magnetic() -> None:
    result = validate_hsa_setpoint(
        HsaCsaSetpoint(heading_deg=90.0, heading_ref="MAGNETIC_NORTH"),
        min_rel_alt_m=10.0,
        max_rel_alt_m=500.0,
        home_hae_m=None,
    )
    assert result is not None
    assert result.validation_results == ("CAPABILITY_NOT_SUPPORTED",)


def test_hsa_rejects_out_of_envelope() -> None:
    result = validate_hsa_setpoint(
        HsaCsaSetpoint(altitude_m=5.0, altitude_ref="AGL"),
        min_rel_alt_m=10.0,
        max_rel_alt_m=500.0,
        home_hae_m=None,
    )
    assert result is not None
    assert result.validation_results == ("PERFORMANCE_LIMIT_EXCEEDED",)


def test_hsa_hae_accepts_0_1m_grid_at_home() -> None:
    home = 489.429
    assert (
        validate_hsa_setpoint(
            HsaCsaSetpoint(altitude_m=489.4, altitude_ref="WGS_HAE"),
            min_rel_alt_m=0.0,
            max_rel_alt_m=500.0,
            home_hae_m=home,
        )
        is None
    )
    assert (
        validate_hsa_setpoint(
            HsaCsaSetpoint(altitude_m=489.5, altitude_ref="WGS_HAE"),
            min_rel_alt_m=0.0,
            max_rel_alt_m=500.0,
            home_hae_m=home,
        )
        is None
    )
    low = validate_hsa_setpoint(
        HsaCsaSetpoint(altitude_m=489.3, altitude_ref="WGS_HAE"),
        min_rel_alt_m=0.0,
        max_rel_alt_m=500.0,
        home_hae_m=home,
    )
    assert low is not None
    assert "489.3m HAE outside [489.4, 989.4]" in (low.reason_description or "")


def test_waypoint_hae_accepts_advertised_tenth() -> None:
    home = 489.429
    assert (
        validate_waypoint_path(
            (Waypoint(10.0, 20.0, 499.4),),
            min_rel_alt_m=10.0,
            max_rel_alt_m=500.0,
            home_hae_m=home,
        )
        is None
    )
