"""The airfield store, and the single-runway view the codec takes.

These replace tests for `home_airfield_from_tspi`, which synthesised a
1,500 m runway on heading 090 wherever the vehicle happened to be.
§1.2.6.3 wants this data "pre-loaded and pre-validated", so it is now
read from a store and the tests are about reading it correctly and
refusing it when it is wrong.
"""

from __future__ import annotations

import pathlib

import pytest

from open_vi.domain import home_view
from open_vi.fa import AirfieldStoreError, default_store_path, load_airfields

MINIMAL = """
[[airfield]]
label = "test-field"

  [[airfield.runway]]
  label = "09"
  direction_deg = 90.0
  available_length_m = 1200.0

    [airfield.runway.takeoff.start]
    latitude_deg = 10.0
    longitude_deg = 20.0

    [airfield.runway.takeoff.limit]
    latitude_deg = 10.0
    longitude_deg = 20.01

    [airfield.runway.landing.start]
    latitude_deg = 10.0
    longitude_deg = 20.01

    [airfield.runway.landing.limit]
    latitude_deg = 10.0
    longitude_deg = 20.0
"""


def _write(tmp_path: pathlib.Path, body: str) -> pathlib.Path:
    store = tmp_path / "airfields.toml"
    store.write_text(body)
    return store


def test_packaged_default_loads() -> None:
    """The shipped store is the demo's field and must stay readable."""
    fields = load_airfields()
    assert fields
    runway = fields[0].primary
    assert runway.available_length_m > 0
    assert 0.0 <= runway.direction_deg < 360.0
    assert runway.takeoff.start is not None


def test_ids_are_stable_across_loads(tmp_path: pathlib.Path) -> None:
    """MA references these by id, so a reload must not renumber them."""
    store = _write(tmp_path, MINIMAL)
    first, second = load_airfields(store), load_airfields(store)
    assert first[0].airfield_id == second[0].airfield_id
    assert first[0].primary.runway_id == second[0].primary.runway_id
    assert (
        first[0].primary.takeoff_route_id == second[0].primary.takeoff_route_id
    )
    assert (
        first[0].primary.takeoff_route_id != first[0].primary.landing_route_id
    )


def test_configured_ids_are_used(tmp_path: pathlib.Path) -> None:
    body = MINIMAL.replace(
        '[[airfield]]\nlabel = "test-field"',
        '[[airfield]]\nlabel = "test-field"\n'
        'id = "11111111-1111-1111-1111-111111111111"',
    )
    field = load_airfields(_write(tmp_path, body))[0]
    assert str(field.airfield_id) == "11111111-1111-1111-1111-111111111111"


def test_missing_store_is_an_error(tmp_path: pathlib.Path) -> None:
    """Never a fallback to a synthesised field -- that is the bug fixed."""
    with pytest.raises(AirfieldStoreError, match="no airfield store"):
        load_airfields(tmp_path / "absent.toml")


@pytest.mark.parametrize(
    ("mutate", "expected"),
    [
        (lambda b: "", "no \\[\\[airfield\\]\\]"),
        (
            lambda b: b.replace(
                "direction_deg = 90.0", "direction_deg = 400.0"
            ),
            "outside \\[0, 360\\)",
        ),
        (
            lambda b: b.replace(
                "available_length_m = 1200.0", "available_length_m = 0"
            ),
            "not positive",
        ),
        (
            lambda b: b.replace("latitude_deg = 10.0", "latitude_deg = 100.0"),
            "latitude_deg",
        ),
        (
            lambda b: b.replace(
                "direction_deg = 90.0", 'direction_deg = "east"'
            ),
            "must be a number",
        ),
        (
            lambda b: b.split("  [[airfield.runway]]")[0],
            "no \\[\\[runway\\]\\]",
        ),
        (
            lambda b: b.replace("[airfield.runway.takeoff.start]", "[unused]"),
            "takeoff is missing|start is missing",
        ),
    ],
)
def test_bad_store_is_refused(
    tmp_path: pathlib.Path, mutate, expected: str
) -> None:
    """Each refusal names where the problem is, not just that there is one."""
    with pytest.raises(AirfieldStoreError, match=expected):
        load_airfields(_write(tmp_path, mutate(MINIMAL)))


def test_home_view_projects_the_primary_runway(
    tmp_path: pathlib.Path,
) -> None:
    """The codec takes one field and one runway; this is that narrowing."""
    field = load_airfields(_write(tmp_path, MINIMAL))[0]
    view = home_view(field)
    runway = field.primary
    assert view.airfield_id == field.airfield_id
    assert view.runway_id == runway.runway_id
    assert view.direction_deg == runway.direction_deg
    assert view.available_length_m == runway.available_length_m
    assert view.takeoff_path == (runway.takeoff.start, runway.takeoff.limit)
    assert view.landing_path == (runway.landing.start, runway.landing.limit)
    # Landing runs back down the strip the takeoff used.
    assert view.landing_start == view.takeoff_end
    assert view.landing_end == view.takeoff_start


def test_default_store_path_is_inside_the_package() -> None:
    path = default_store_path()
    assert path.name == "airfields.toml"
    assert path.parent.name == "fa"
