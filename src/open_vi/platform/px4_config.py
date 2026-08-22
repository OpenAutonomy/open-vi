"""User-asserted PX4 vehicle facts a running instance does not publish.

The adapter copies these onto ``snapshot()`` / ``get_vehicle_state()``.
Isolator publishes whatever the port returns. This module does not
talk to PX4 or check the values against the vehicle.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from open_vi.domain import AccelerationLimit, AirspeedLimit, FlightModeProfile

try:
    import tomllib
except ImportError:  # pragma: no cover - 3.11+ is required
    tomllib = None  # type: ignore[assignment]


_SPEED_REFS = frozenset({"GROUNDSPEED", "TRUE_AIRSPEED", "CALIBRATED_AIRSPEED"})
_ALT_REFS = frozenset({"WGS_HAE", "AGL", "MSL", "ALTITUDE_BAROMETRIC"})
_TOP_KEYS = frozenset({"fuel_mass_kg", "envelope", "performance"})
_ENVELOPE_KEYS = frozenset({"min_rel_alt_m", "max_rel_alt_m"})
_PERF_KEYS = frozenset(
    {
        "min_airspeed",
        "max_airspeed",
        "best_endurance_airspeed",
        "best_range_airspeed",
        "min_acceleration",
        "max_acceleration",
        "max_turn_rate_rps",
        "max_climb_rate_mps",
        "max_descent_rate_mps",
    }
)
_AIRSPEED_KEYS = frozenset(
    {"speed_mps", "altitude_m", "reference", "altitude_ref", "weight_kg"}
)
_ACCEL_KEYS = frozenset(
    {
        "x_mps2",
        "y_mps2",
        "z_mps2",
        "mach",
        "roll_rate_rps",
        "pitch_rate_rps",
        "yaw_rate_rps",
    }
)


@dataclass(frozen=True)
class Px4VehicleConfig:
    """Static PX4 facts that are not live MAVLink telemetry."""

    fuel_mass_kg: float | None = None
    min_rel_alt_m: float | None = None
    max_rel_alt_m: float | None = None
    profile: FlightModeProfile = FlightModeProfile()


def load_px4_vehicle_config(path: str | Path) -> Px4VehicleConfig:
    """Parse a PX4 vehicle TOML file.

    Raises ``FileNotFoundError`` when *path* is missing,
    ``ValueError`` when the file is not valid vehicle TOML.
    """
    if tomllib is None:  # pragma: no cover
        raise RuntimeError("tomllib is required (Python 3.11+)")
    config_path = Path(path)
    try:
        raw_text = config_path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(
            f"PX4 vehicle config not found: {config_path}"
        ) from exc
    try:
        data = tomllib.loads(raw_text)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"PX4 vehicle config is not valid TOML: {config_path}: {exc}"
        ) from exc
    if not isinstance(data, dict):
        raise ValueError(f"PX4 vehicle config must be a table: {config_path}")
    try:
        return _parse_vehicle(data)
    except ValueError as exc:
        raise ValueError(f"{config_path}: {exc}") from exc


def _parse_vehicle(data: dict[str, Any]) -> Px4VehicleConfig:
    _reject_unknown("config", data, _TOP_KEYS)
    fuel = _optional_float(data, "fuel_mass_kg")
    if fuel is not None and fuel < 0.0:
        raise ValueError("fuel_mass_kg must be >= 0")
    envelope = data.get("envelope", {})
    if envelope is None:
        envelope = {}
    if not isinstance(envelope, dict):
        raise ValueError("envelope must be a table")
    _reject_unknown("envelope", envelope, _ENVELOPE_KEYS)
    performance = data.get("performance", {})
    if performance is None:
        performance = {}
    if not isinstance(performance, dict):
        raise ValueError("performance must be a table")
    _reject_unknown("performance", performance, _PERF_KEYS)
    return Px4VehicleConfig(
        fuel_mass_kg=fuel,
        min_rel_alt_m=_optional_float(envelope, "min_rel_alt_m"),
        max_rel_alt_m=_optional_float(envelope, "max_rel_alt_m"),
        profile=_parse_profile(performance),
    )


def _parse_profile(data: dict[str, Any]) -> FlightModeProfile:
    return FlightModeProfile(
        min_airspeed=_airspeed_list(data, "min_airspeed"),
        max_airspeed=_airspeed_list(data, "max_airspeed"),
        best_endurance_airspeed=_airspeed_list(data, "best_endurance_airspeed"),
        best_range_airspeed=_airspeed_list(data, "best_range_airspeed"),
        min_acceleration=_accel_list(data, "min_acceleration"),
        max_acceleration=_accel_list(data, "max_acceleration"),
        max_turn_rate_rps=_optional_float(data, "max_turn_rate_rps"),
        max_climb_rate_mps=_optional_float(data, "max_climb_rate_mps"),
        max_descent_rate_mps=_optional_float(data, "max_descent_rate_mps"),
    )


def _airspeed_list(data: dict[str, Any], key: str) -> tuple[AirspeedLimit, ...]:
    if key not in data or data[key] is None:
        return ()
    rows = data[key]
    if not isinstance(rows, list):
        raise ValueError(f"performance.{key} must be an array of tables")
    return tuple(
        _parse_airspeed(f"performance.{key}[{index}]", row)
        for index, row in enumerate(rows)
    )


def _parse_airspeed(where: str, row: Any) -> AirspeedLimit:
    if not isinstance(row, dict):
        raise ValueError(f"{where} must be a table")
    _reject_unknown(where, row, _AIRSPEED_KEYS)
    speed = _require_float(row, "speed_mps", where)
    if speed < 0.0:
        raise ValueError(f"{where}.speed_mps must be >= 0")
    altitude = _require_float(row, "altitude_m", where)
    reference = _enum(
        row.get("reference", "TRUE_AIRSPEED"),
        _SPEED_REFS,
        f"{where}.reference",
    )
    altitude_ref = _enum(
        row.get("altitude_ref", "AGL"),
        _ALT_REFS,
        f"{where}.altitude_ref",
    )
    weight = _optional_float(row, "weight_kg")
    if weight is not None and weight < 0.0:
        raise ValueError(f"{where}.weight_kg must be >= 0")
    return AirspeedLimit(
        speed_mps=speed,
        altitude_m=altitude,
        speed_ref=reference,
        altitude_ref=altitude_ref,
        weight_kg=weight,
    )


def _accel_list(
    data: dict[str, Any], key: str
) -> tuple[AccelerationLimit, ...]:
    if key not in data or data[key] is None:
        return ()
    rows = data[key]
    if not isinstance(rows, list):
        raise ValueError(f"performance.{key} must be an array of tables")
    return tuple(
        _parse_accel(f"performance.{key}[{index}]", row)
        for index, row in enumerate(rows)
    )


def _parse_accel(where: str, row: Any) -> AccelerationLimit:
    if not isinstance(row, dict):
        raise ValueError(f"{where} must be a table")
    _reject_unknown(where, row, _ACCEL_KEYS)
    has_mach = "mach" in row
    has_rates = any(
        key in row
        for key in ("roll_rate_rps", "pitch_rate_rps", "yaw_rate_rps")
    )
    if has_mach == has_rates:
        raise ValueError(
            f"{where} must set mach or roll/pitch/yaw_rate_rps, not both"
        )
    if has_rates:
        missing = [
            key
            for key in ("roll_rate_rps", "pitch_rate_rps", "yaw_rate_rps")
            if key not in row
        ]
        if missing:
            joined = ", ".join(missing)
            raise ValueError(f"{where} rate pair requires {joined}")
    return AccelerationLimit(
        x_mps2=_require_float(row, "x_mps2", where),
        y_mps2=_require_float(row, "y_mps2", where),
        z_mps2=_require_float(row, "z_mps2", where),
        mach=_optional_float(row, "mach") if has_mach else None,
        roll_rate_rps=(
            _require_float(row, "roll_rate_rps", where) if has_rates else None
        ),
        pitch_rate_rps=(
            _require_float(row, "pitch_rate_rps", where) if has_rates else None
        ),
        yaw_rate_rps=(
            _require_float(row, "yaw_rate_rps", where) if has_rates else None
        ),
    )


def _reject_unknown(
    where: str, data: dict[str, Any], allowed: frozenset[str]
) -> None:
    unknown = sorted(set(data) - allowed)
    if unknown:
        joined = ", ".join(unknown)
        raise ValueError(f"{where} has unknown keys: {joined}")


def _enum(value: Any, allowed: frozenset[str], where: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{where} must be a string")
    token = value.strip().upper().replace("-", "_")
    if token not in allowed:
        joined = ", ".join(sorted(allowed))
        raise ValueError(f"{where} must be one of {joined}")
    return token


def _optional_float(data: dict[str, Any], key: str) -> float | None:
    if key not in data or data[key] is None:
        return None
    return _as_float(data[key], key)


def _require_float(data: dict[str, Any], key: str, where: str) -> float:
    if key not in data:
        raise ValueError(f"{where}.{key} is required")
    return _as_float(data[key], f"{where}.{key}")


def _as_float(value: Any, where: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{where} must be a number")
    out = float(value)
    if not math.isfinite(out):
        raise ValueError(f"{where} must be finite")
    return out
