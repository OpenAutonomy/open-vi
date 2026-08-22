"""PX4 vehicle TOML: parse, reject, and apply to the adapter."""

from __future__ import annotations

from pathlib import Path

import pytest

from open_vi.platform.px4 import Px4MavlinkAdapter
from open_vi.platform.px4_config import (
    Px4VehicleConfig,
    load_px4_vehicle_config,
)

EXAMPLE = Path(__file__).resolve().parents[1] / "examples" / "px4-vehicle.toml"


def _write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "vehicle.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_example_vehicle_toml_loads() -> None:
    cfg = load_px4_vehicle_config(EXAMPLE)
    assert cfg.min_rel_alt_m == pytest.approx(10.0)
    assert cfg.max_rel_alt_m == pytest.approx(500.0)
    assert len(cfg.profile.max_airspeed) == 2
    assert cfg.profile.max_airspeed[0].speed_ref == "GROUNDSPEED"
    assert cfg.profile.max_acceleration[0].mach == pytest.approx(0.0)
    assert cfg.profile.max_climb_rate_mps == pytest.approx(5.0)


def test_empty_toml_is_empty_config(tmp_path: Path) -> None:
    cfg = load_px4_vehicle_config(_write(tmp_path, ""))
    assert cfg == Px4VehicleConfig()


def test_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not found"):
        load_px4_vehicle_config(tmp_path / "missing.toml")


def test_unknown_key_raises(tmp_path: Path) -> None:
    path = _write(tmp_path, "dry_mass_kg = 10\n")
    with pytest.raises(ValueError, match="unknown keys"):
        load_px4_vehicle_config(path)


def test_remaining_fuel_is_not_a_config_field(tmp_path: Path) -> None:
    path = _write(tmp_path, "fuel_mass_kg = 2.5\n")
    with pytest.raises(ValueError, match="unknown keys"):
        load_px4_vehicle_config(path)


def test_bad_speed_ref_raises(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[[performance.min_airspeed]]
speed_mps = 1
altitude_m = 0
reference = "INDICATED"
""",
    )
    with pytest.raises(ValueError, match="reference"):
        load_px4_vehicle_config(path)


def test_accel_requires_pair(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        """
[[performance.max_acceleration]]
x_mps2 = 1
y_mps2 = 1
z_mps2 = 1
""",
    )
    with pytest.raises(ValueError, match="mach or roll/pitch/yaw"):
        load_px4_vehicle_config(path)


def test_adapter_loads_config_path() -> None:
    plat = Px4MavlinkAdapter(
        connection=None, autoconnect=False, config_path=str(EXAMPLE)
    )
    assert plat.get_vehicle_state().fuel_mass_kg is None
    profile = plat.snapshot().offer.waypoint_profile
    assert profile is not None
    assert profile.max_climb_rate_mps == pytest.approx(5.0)
    plat.close()


def test_adapter_applies_config_curves() -> None:
    cfg = load_px4_vehicle_config(EXAMPLE)
    plat = Px4MavlinkAdapter(connection=None, autoconnect=False, config=cfg)
    assert plat.get_vehicle_state().fuel_mass_kg is None
    profile = plat.snapshot().offer.waypoint_profile
    assert profile is not None
    assert profile.min_altitude_m == pytest.approx(10.0)
    assert profile.max_altitude_m == pytest.approx(500.0)
    assert profile.altitude_ref == "AGL"
    assert len(profile.max_airspeed) == 2
    assert profile.max_airspeed[0].altitude_ref == "AGL"
    assert profile.max_climb_rate_mps == pytest.approx(5.0)
    plat.close()


def test_constructor_envelope_wins_over_config() -> None:
    cfg = Px4VehicleConfig(min_rel_alt_m=20.0, max_rel_alt_m=80.0)
    plat = Px4MavlinkAdapter(
        connection=None,
        autoconnect=False,
        config=cfg,
        min_rel_alt_m=15.0,
        max_rel_alt_m=60.0,
    )
    profile = plat.snapshot().offer.waypoint_profile
    assert profile is not None
    assert profile.min_altitude_m == pytest.approx(15.0)
    assert profile.max_altitude_m == pytest.approx(60.0)
    plat.close()
