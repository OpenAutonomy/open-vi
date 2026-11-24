"""Validate the outbound corpus against the A-GRA XSD catalog.

The standard is public — Distribution Statement A — but it is not
redistributed here, the same stance ``oa-gateway`` and ``open-ma``
take. Fetch it, pinned by digest to the same revision oa-gateway
checks against:

    pip install -e ".[validate]"
    ./scripts/fetch-agra-schema.sh
    pytest tests/test_wire_xsd.py

The schema lands in ``schema/a-gra/`` (gitignored) and is found there
automatically. ``UCI_XSD`` overrides the path for a program-specific
Message Set or an offline mirror.

One path is enough: the processor resolves ``xs:include`` /
``xs:import`` itself relative to the entry document, so
``A-GRA_MessageDefinitions_v5_0_a.xsd`` spans the catalog. Without a
schema the module skips, so the suite is green before anyone fetches
one.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from wire_helpers import capture_corpus

XSD_ENV = "UCI_XSD"
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_XSD = (
    _REPO_ROOT / "schema" / "a-gra" / "A-GRA_MessageDefinitions_v5_0_a.xsd"
)

# Builders that do not yet match A-GRA v5.0a. Measured against the
# fetched catalog, not assumed. Each is a real wire-format defect:
#
#   the plan-execution family emits flat fields where the schema has a
#   PlanExecutionStatus composite, and ExecutingSystemID where the
#   schema says SystemID;
#
#   MA_RoutePlan puts Path directly under MessageData with no Plan
#   wrapper, and orders ForPlanningUseOnly before it rather than after.
#
# This registry exists so the gate is usable while those builders are
# fixed, not to excuse them. The assertions below are strict in both
# directions: a newly non-conformant type fails, and so does one that
# starts validating while still listed here.
KNOWN_NON_CONFORMANT = {
    "MA_MissionPlanExecutionStatus",
    "MA_RoutePlan",
    "ResponsePlanExecutionStatus",
    "RoutePlanExecutionStatus",
}


def _xsd_path() -> pathlib.Path | None:
    """``UCI_XSD`` if set, else the fetched catalog, else ``None``."""
    raw = os.environ.get(XSD_ENV, "").strip()
    if raw:
        path = pathlib.Path(raw).expanduser()
        return path if path.is_file() else None
    return DEFAULT_XSD if DEFAULT_XSD.is_file() else None


pytestmark = pytest.mark.skipif(
    _xsd_path() is None,
    reason=(
        "no A-GRA catalog: run ./scripts/fetch-agra-schema.sh, or set "
        f"{XSD_ENV} to an entry document"
    ),
)


@pytest.fixture(scope="module")
def schema():
    xmlschema = pytest.importorskip(
        "xmlschema",
        reason="pip install -e '.[validate]' to enable XSD validation",
    )
    path = _xsd_path()
    assert path is not None
    return xmlschema.XMLSchema(str(path))


@pytest.fixture(scope="module")
def corpus() -> dict[str, list[str]]:
    mp = pytest.MonkeyPatch()
    try:
        return capture_corpus(mp)
    finally:
        mp.undo()


def _errors(schema, bodies: list[str]) -> list[str]:
    found: list[str] = []
    for index, body in enumerate(bodies):
        for error in schema.iter_errors(body):
            found.append(
                f"[{index}] {error.path}: {error.reason.splitlines()[0]}"
            )
    return found


def test_schema_declares_our_root_elements(schema, corpus) -> None:
    """The catalog must actually cover the messages we publish."""
    undeclared = sorted(mt for mt in corpus if mt not in schema.elements)
    assert not undeclared, (
        f"catalog declares no global element for {undeclared}; is "
        f"{XSD_ENV} the A-GRA entry document?"
    )


def test_conformant_types_validate(schema, corpus) -> None:
    """Every message type outside the known-gap registry is schema-valid."""
    failures: list[str] = []
    for message_type, bodies in sorted(corpus.items()):
        if message_type in KNOWN_NON_CONFORMANT:
            continue
        for detail in _errors(schema, bodies)[:3]:
            failures.append(f"{message_type}{detail}")
    assert not failures, "schema validation failed:\n" + "\n".join(
        failures[:40]
    )


def test_known_gaps_have_not_been_fixed_silently(schema, corpus) -> None:
    """A listed type that now validates must be removed from the registry.

    Keeps the registry from outliving the defects it records.
    """
    fixed = sorted(
        mt
        for mt in KNOWN_NON_CONFORMANT
        if mt in corpus and not _errors(schema, corpus[mt])
    )
    assert not fixed, (
        f"{fixed} now validate; drop them from KNOWN_NON_CONFORMANT"
    )


def test_known_gaps_are_still_published(corpus) -> None:
    """A listed type that is no longer published is a stale entry."""
    stale = sorted(KNOWN_NON_CONFORMANT - set(corpus))
    assert not stale, f"{stale} are no longer published; drop them"
