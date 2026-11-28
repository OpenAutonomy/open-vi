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


TWO_FIELDS = (
    MINIMAL
    + """
[[airfield]]
label = "alternate"

  [[airfield.runway]]
  label = "27"
  direction_deg = 270.0
  available_length_m = 900.0

    [airfield.runway.takeoff.start]
    latitude_deg = 11.0
    longitude_deg = 21.0

    [airfield.runway.takeoff.limit]
    latitude_deg = 11.0
    longitude_deg = 20.99

    [airfield.runway.landing.start]
    latitude_deg = 11.0
    longitude_deg = 20.99

    [airfield.runway.landing.limit]
    latitude_deg = 11.0
    longitude_deg = 21.0
"""
)


def test_the_whole_store_reaches_the_context(tmp_path: pathlib.Path) -> None:
    """Isolator keeps the load, not just the narrowed view.

    Vetting will need the runway start and status, and re-reading the
    file would be a second load path that could disagree with the
    first.
    """
    from open_vi.asb import InMemoryAsb
    from open_vi.config import IsolatorConfig
    from open_vi.isolator import Isolator
    from open_vi.platform import StubPlatform

    store = _write(tmp_path, MINIMAL)
    iso = Isolator(
        InMemoryAsb(),
        platform=StubPlatform(),
        config=IsolatorConfig(airfield_store=str(store)),
    )
    assert len(iso.ctx.airfields) == 1
    runway = iso.ctx.airfields[0].primary
    assert runway.status == "OPERATIONAL"
    assert runway.takeoff.start.latitude_deg == 10.0
    # The narrowed view stays the codec's input and agrees with it.
    assert iso.ctx.airfield.runway_id == runway.runway_id


def test_extra_airfields_are_reported_not_silently_dropped(
    tmp_path: pathlib.Path, caplog
) -> None:
    """§1.2.6.3 asks for alternates; the codec still emits one field.

    Loading several and serving one without saying so would look like
    the alternates were being reported.
    """
    import logging

    from open_vi.asb import InMemoryAsb
    from open_vi.config import IsolatorConfig
    from open_vi.isolator import Isolator
    from open_vi.platform import StubPlatform

    store = _write(tmp_path, TWO_FIELDS)
    with caplog.at_level(logging.WARNING):
        iso = Isolator(
            InMemoryAsb(),
            platform=StubPlatform(),
            config=IsolatorConfig(airfield_store=str(store)),
        )
    assert len(iso.ctx.airfields) == 2
    assert iso.ctx.airfield.runway_id == iso.ctx.airfields[0].primary.runway_id
    assert any(
        "holds 2 airfields" in record.message for record in caplog.records
    ), "serving one of several airfields was not reported"


def test_a_bad_store_stops_the_isolator(tmp_path: pathlib.Path) -> None:
    """Never a fallback to a synthesised field."""
    from open_vi.asb import InMemoryAsb
    from open_vi.config import IsolatorConfig
    from open_vi.isolator import Isolator
    from open_vi.platform import StubPlatform

    with pytest.raises(AirfieldStoreError):
        Isolator(
            InMemoryAsb(),
            platform=StubPlatform(),
            config=IsolatorConfig(airfield_store=str(tmp_path / "nope.toml")),
        )
