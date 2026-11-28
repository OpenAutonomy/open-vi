"""Read the pre-validated airfield and TO/L route store.

§1.2.6.3 has MA query FA for "pre-loaded and pre-validated Airfield
and Take off and Landing (TO/L) route information stored within FA",
and §1.2.5.2 forbids MA uploading route plans for takeoff, departure,
approach or landing. So this data is loaded, never computed: a runway
derived at startup is validated by nobody, which is the property those
clauses exist to protect.

Validation is the supplier's responsibility. Whoever writes a runway
into the store is the one who validated it; this module checks the
file parses and is internally consistent, nothing more. It does not
make the data correct and must not be read as doing so.

TOML and degrees rather than A-GRA XML. An XML store could be checked
against the XSD directly, but radians are not reviewable by hand,
parsing XML here would cross the no-codec boundary this package
depends on, and the conformance job already validates the emitted
``AirfieldReport``. The schema still catches a bad value, one step
later, on the message that has to be conformant.
"""

from __future__ import annotations

import pathlib
import tomllib
import uuid
from typing import Any

from open_vi.domain import Airfield, Runway, RunwayCoordinates, Waypoint

_DEFAULT = "airfields.toml"


class AirfieldStoreError(RuntimeError):
    """The store is missing, unparseable, or internally inconsistent.

    Raised rather than falling back to a synthesised field: a
    fabricated runway is exactly what this replaces, and failing at
    startup is where that failure is loud.
    """


def default_store_path() -> pathlib.Path:
    """The store shipped with the package."""
    return pathlib.Path(__file__).resolve().parent / _DEFAULT


def load_airfields(
    path: pathlib.Path | str | None = None,
) -> tuple[Airfield, ...]:
    """Load airfields from *path*, or the packaged default.

    Raises:
        AirfieldStoreError: the file is absent, does not parse, or
            describes an airfield that cannot be used -- no runways, a
            runway with no takeoff start, a direction outside
            [0, 360), or a non-positive length.
    """
    store = pathlib.Path(path) if path is not None else default_store_path()
    if not store.is_file():
        raise AirfieldStoreError(f"no airfield store at {store}")
    try:
        raw = tomllib.loads(store.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise AirfieldStoreError(f"{store}: {exc}") from exc

    entries = raw.get("airfield")
    if not isinstance(entries, list) or not entries:
        raise AirfieldStoreError(f"{store}: no [[airfield]] entries")
    return tuple(
        _airfield(entry, store, index) for index, entry in enumerate(entries)
    )


def _airfield(entry: Any, store: pathlib.Path, index: int) -> Airfield:
    where = f"{store}: airfield[{index}]"
    label = _text(entry, "label", where, default="home")
    runways = entry.get("runway")
    if not isinstance(runways, list) or not runways:
        raise AirfieldStoreError(f"{where} ({label}) has no [[runway]]")
    field_id = _id(entry, "id", where, seed=f"airfield:{label}")
    return Airfield(
        airfield_id=field_id,
        report_id=_id(
            entry, "report_id", where, seed=f"airfield-report:{label}"
        ),
        label=label,
        runways=tuple(
            _runway(runway, f"{where}.runway[{n}]", label)
            for n, runway in enumerate(runways)
        ),
    )


def _runway(entry: Any, where: str, airfield_label: str) -> Runway:
    label = _text(entry, "label", where, default="runway")
    direction = _number(entry, "direction_deg", where)
    if not 0.0 <= direction < 360.0:
        raise AirfieldStoreError(
            f"{where}: direction_deg {direction} outside [0, 360)"
        )
    length = _number(entry, "available_length_m", where)
    if length <= 0.0:
        raise AirfieldStoreError(
            f"{where}: available_length_m {length} is not positive"
        )
    seed = f"{airfield_label}/{label}"
    return Runway(
        runway_id=_id(entry, "id", where, seed=f"runway:{seed}"),
        direction_deg=direction,
        available_length_m=length,
        status=_text(entry, "status", where, default="OPERATIONAL"),
        label=label,
        takeoff=_coordinates(entry.get("takeoff"), f"{where}.takeoff"),
        landing=_coordinates(entry.get("landing"), f"{where}.landing"),
        takeoff_route_id=_id(
            entry, "takeoff_route_id", where, seed=f"takeoff:{seed}"
        ),
        landing_route_id=_id(
            entry, "landing_route_id", where, seed=f"landing:{seed}"
        ),
    )


def _coordinates(entry: Any, where: str) -> RunwayCoordinates:
    if not isinstance(entry, dict):
        raise AirfieldStoreError(f"{where} is missing")
    start = entry.get("start")
    if not isinstance(start, dict):
        raise AirfieldStoreError(f"{where}.start is missing")
    return RunwayCoordinates(
        start=_waypoint(start, f"{where}.start"),
        threshold=(
            _waypoint(entry["threshold"], f"{where}.threshold")
            if isinstance(entry.get("threshold"), dict)
            else None
        ),
        limit=(
            _waypoint(entry["limit"], f"{where}.limit")
            if isinstance(entry.get("limit"), dict)
            else None
        ),
    )


def _waypoint(entry: Any, where: str) -> Waypoint:
    latitude = _number(entry, "latitude_deg", where)
    longitude = _number(entry, "longitude_deg", where)
    if not -90.0 <= latitude <= 90.0:
        raise AirfieldStoreError(f"{where}: latitude_deg {latitude}")
    if not -180.0 <= longitude <= 180.0:
        raise AirfieldStoreError(f"{where}: longitude_deg {longitude}")
    altitude = entry.get("altitude_m")
    return Waypoint(
        latitude_deg=latitude,
        longitude_deg=longitude,
        altitude_m=float(altitude) if altitude is not None else None,
    )


def _text(entry: Any, key: str, where: str, *, default: str) -> str:
    value = entry.get(key, default)
    if not isinstance(value, str) or not value:
        raise AirfieldStoreError(f"{where}: {key} must be a non-empty string")
    return value


def _number(entry: Any, key: str, where: str) -> float:
    value = entry.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise AirfieldStoreError(f"{where}: {key} must be a number")
    return float(value)


def _id(entry: Any, key: str, where: str, *, seed: str) -> uuid.UUID:
    """A configured UUID, or a stable one derived from *seed*.

    Ids may be omitted so a store is readable without generating
    UUIDs by hand. A derived id is stable across runs, which matters
    because MA references these by id.
    """
    raw = entry.get(key)
    if raw is None:
        return uuid.uuid5(uuid.NAMESPACE_URL, f"open-vi:{seed}")
    if not isinstance(raw, str):
        raise AirfieldStoreError(f"{where}: {key} must be a UUID string")
    try:
        return uuid.UUID(raw)
    except ValueError as exc:
        raise AirfieldStoreError(f"{where}: {key} is not a UUID") from exc
