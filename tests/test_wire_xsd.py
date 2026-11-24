"""Validate the outbound corpus against the UCI / A-GRA XSD catalog.

The schemas are not in this repository and are not redistributed with
it. They are operator-supplied: point ``UCI_XSD_DIR`` at a directory
holding the catalog and this module validates every message open-vi
publishes against it. Without that variable the whole module skips, so
the suite stays green for contributors who do not have the catalog.

    pip install -e ".[validate]"
    UCI_XSD_DIR=/path/to/catalog pytest tests/test_wire_xsd.py

Schema resolution, in order:

* ``$UCI_XSD_DIR/<MessageType>.xsd`` — one schema per message type.
* ``$UCI_XSD_MASTER`` — a single entry schema used for every message,
  for a catalog that imports its types from one root.

Nothing here asserts a catalog layout the project has not seen; an
unresolvable message is reported, not silently passed.
"""

from __future__ import annotations

import os
import pathlib

import pytest

from wire_helpers import capture_corpus

XSD_DIR_ENV = "UCI_XSD_DIR"
XSD_MASTER_ENV = "UCI_XSD_MASTER"


def _xsd_dir() -> pathlib.Path | None:
    raw = os.environ.get(XSD_DIR_ENV, "").strip()
    if not raw:
        return None
    path = pathlib.Path(raw).expanduser()
    return path if path.is_dir() else None


pytestmark = pytest.mark.skipif(
    _xsd_dir() is None,
    reason=(
        f"{XSD_DIR_ENV} is unset or not a directory; the UCI/A-GRA XSD "
        "catalog is operator-supplied and not vendored in this repo"
    ),
)


@pytest.fixture(scope="module")
def validator_for():
    """Return ``(message_type) -> schema`` or skip if unusable."""
    xmlschema = pytest.importorskip(
        "xmlschema",
        reason="pip install -e '.[validate]' to enable XSD validation",
    )
    directory = _xsd_dir()
    assert directory is not None
    master = os.environ.get(XSD_MASTER_ENV, "").strip()
    master_schema = None
    if master:
        master_path = pathlib.Path(master).expanduser()
        if not master_path.is_file():
            pytest.fail(f"{XSD_MASTER_ENV}={master} is not a file")
        master_schema = xmlschema.XMLSchema(str(master_path))

    cache: dict[str, object] = {}

    def resolve(message_type: str):
        if message_type in cache:
            return cache[message_type]
        per_type = directory / f"{message_type}.xsd"
        if per_type.is_file():
            schema = xmlschema.XMLSchema(str(per_type))
        elif master_schema is not None:
            schema = master_schema
        else:
            schema = None
        cache[message_type] = schema
        return schema

    return resolve


@pytest.fixture(scope="module")
def corpus() -> dict[str, list[str]]:
    mp = pytest.MonkeyPatch()
    try:
        return capture_corpus(mp)
    finally:
        mp.undo()


def test_catalog_resolves_every_message_type(
    corpus: dict[str, list[str]], validator_for
) -> None:
    """Report unresolvable types rather than quietly skipping them."""
    unresolved = sorted(mt for mt in corpus if validator_for(mt) is None)
    assert not unresolved, (
        f"no schema found for {unresolved} — expected "
        f"$<{XSD_DIR_ENV}>/<MessageType>.xsd or ${XSD_MASTER_ENV}"
    )


def test_every_published_message_validates(
    corpus: dict[str, list[str]], validator_for
) -> None:
    """Every body open-vi puts on the bus is schema-valid."""
    failures: list[str] = []
    for message_type, bodies in corpus.items():
        schema = validator_for(message_type)
        if schema is None:
            continue
        for index, body in enumerate(bodies):
            errors = list(schema.iter_errors(body))
            for error in errors[:3]:
                failures.append(
                    f"{message_type}[{index}] {error.path}: {error.reason}"
                )
    assert not failures, "schema validation failed:\n" + "\n".join(
        failures[:40]
    )
