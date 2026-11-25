"""Pin the §1.2 interaction-table parse.

:mod:`spec_interactions` reads obligations out of a PDF text layer, so
it can degrade in two directions: it can stop finding rows, or it can
start inventing them out of neighbouring prose. Both would be silent.
These tests fix the shape of a correct parse — the counts, the two
spec defects it must keep reporting, and the bijection onto the
interactions FEATURES documents — so a changed volume fails loudly.
"""

from __future__ import annotations

import pathlib
import re
import unicodedata

import pytest

import spec_interactions

_FEATURES = pathlib.Path(__file__).resolve().parents[1] / "docs" / "FEATURES.md"
_FEATURES_ROW = re.compile(r"^\| (1\.2\.\d+\.\d+) \| ([^|]+?) \|", re.M)


def _slug(text: str) -> str:
    """Compare interaction names across en/em dashes and spacing."""
    folded = unicodedata.normalize("NFKD", text).lower()
    return re.sub(r"[^a-z0-9]+", "", folded)


@pytest.fixture(scope="module")
def interactions() -> tuple[spec_interactions.Interaction, ...]:
    loaded = spec_interactions.load()
    if loaded is None:
        pytest.skip(
            "no Vehicle Interface Volume: run ./scripts/fetch-agra-spec.sh"
        )
    return loaded


def test_counts_are_the_recorded_ones(interactions) -> None:
    """``load`` raises on a mismatch; this names the numbers in the suite."""
    assert len(interactions) == spec_interactions.EXPECTED_TABLES
    messages = [m for i in interactions for m in i.messages]
    assert len(messages) == spec_interactions.EXPECTED_MESSAGES
    assert (
        sum(len(m.required_fields) for m in messages)
        == spec_interactions.EXPECTED_FIELDS
    )
    assert (
        sum(len(m.required_values) for m in messages)
        == spec_interactions.EXPECTED_ENUMS
    )


def test_only_the_recorded_tables_are_empty(interactions) -> None:
    """A table that loses its rows to a parse regression looks empty."""
    empty = {i.table for i in interactions if not i.messages}
    assert empty == set(spec_interactions.EMPTY_TABLES)


def test_label_type_mismatches_are_exactly_as_recorded(interactions) -> None:
    """The volume's two label/type typos, still present and still only two.

    Recorded rather than corrected: a parser that silently repaired
    them would also hide a third one appearing.
    """
    found = {
        i.table: (m.message_type, m.declared_type)
        for i in interactions
        for m in i.messages
        if m.declared_type != m.message_type
    }
    assert found == spec_interactions.LABEL_TYPE_MISMATCHES


def test_every_table_matches_one_documented_interaction(interactions) -> None:
    """The oracle's domain is exactly FEATURES §1.2.

    Catches both directions: a table with no row to govern, and a row
    claiming an interaction the volume does not define.
    """
    documented = {
        _slug(name): section
        for section, name in _FEATURES_ROW.findall(_FEATURES.read_text())
    }
    parsed = {_slug(i.caption): i.table for i in interactions}
    assert not sorted(set(parsed) - set(documented)), (
        "tables with no FEATURES §1.2 row: "
        f"{sorted(parsed[k] for k in set(parsed) - set(documented))}"
    )
    assert not sorted(set(documented) - set(parsed)), (
        "FEATURES §1.2 rows with no table: "
        f"{sorted(documented[k] for k in set(documented) - set(parsed))}"
    )


def test_message_types_shed_their_instance_suffix(interactions) -> None:
    """``...StatusMT_2`` is the second instance of one type, not a type."""
    for message in (m for i in interactions for m in i.messages):
        assert not re.search(r"_\d+$", message.message_type), message.label
        assert message.message_type.endswith("MT"), message.label
        assert not message.element_name.endswith("MT"), message.label


def test_required_fields_are_name_and_type_pairs(interactions) -> None:
    """No empty names, and no ``None`` leaking in as a field or type.

    "None" is how the volume writes an empty Required Fields cell. An
    earlier parse turned it into a field, which is the failure mode
    this guards.
    """
    for table, message, field in spec_interactions.required_fields():
        where = f"{table} {message.label}"
        assert field.name and field.name != "None", where
        assert field.type_name and field.type_name != "None", where
        assert not field.name.endswith(":"), where


def test_required_values_are_enum_tokens(interactions) -> None:
    """A required value is an A-GRA enum token: upper case and bare."""
    for message in (m for i in interactions for m in i.messages):
        for value in message.required_values:
            assert re.fullmatch(r"[A-Z][A-Z0-9_]*", value), (
                f"{message.label}: {value!r}"
            )


def test_fields_not_in_type_are_still_claimed_by_the_volume(
    interactions,
) -> None:
    """The MA_ControlAssignment rows the content model cannot satisfy.

    Kept as a registry so that if a later volume moves them onto
    ``ControlStatus`` — where their own type column already says they
    belong — this fails and the exemption comes off.
    """
    claimed = {
        (i.table, m.message_type, f.name)
        for i in interactions
        for m in i.messages
        for f in m.required_fields
    }
    stale = sorted(spec_interactions.FIELDS_NOT_IN_TYPE - claimed)
    assert not stale, f"no longer required by the volume: {stale}"
