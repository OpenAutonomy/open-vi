"""Byte-exact golden corpus for every message open-vi publishes.

The wire format is the product. These snapshots make any change to it
visible in review rather than implicit: if a builder starts emitting a
different element order, drops a field, or renames a token, the diff
shows up here attached to the commit that caused it.

Regenerate deliberately, never reflexively:

    UPDATE_GOLDEN=1 pytest tests/test_wire_golden.py

and read the resulting diff before committing it.
"""

from __future__ import annotations

import difflib
import os
import pathlib

import pytest

from wire_helpers import capture_corpus

GOLDEN_DIR = pathlib.Path(__file__).parent / "golden"
SEPARATOR = "\n<!--+-->\n"


@pytest.fixture(scope="module")
def corpus() -> dict[str, list[str]]:
    mp = pytest.MonkeyPatch()
    try:
        return capture_corpus(mp)
    finally:
        mp.undo()


def _path(message_type: str) -> pathlib.Path:
    return GOLDEN_DIR / f"{message_type}.xml"


def _readable_diff(expected: str, actual: str) -> str:
    """Split on element boundaries so a one-line body diffs legibly."""
    exp = expected.replace("><", ">\n<").splitlines()
    act = actual.replace("><", ">\n<").splitlines()
    return "\n".join(
        difflib.unified_diff(exp, act, "golden", "captured", lineterm="", n=2)
    )


def test_golden_corpus_matches(corpus: dict[str, list[str]]) -> None:
    """Every published body equals its recorded snapshot."""
    if os.environ.get("UPDATE_GOLDEN"):
        GOLDEN_DIR.mkdir(exist_ok=True)
        for message_type, bodies in corpus.items():
            _path(message_type).write_text(SEPARATOR.join(bodies) + "\n")
        pytest.skip(f"regenerated {len(corpus)} golden files")

    missing = [mt for mt in corpus if not _path(mt).exists()]
    assert not missing, (
        f"no golden file for {missing}; run UPDATE_GOLDEN=1 pytest"
    )

    for message_type, bodies in corpus.items():
        stored = _path(message_type).read_text().rstrip("\n")
        expected = stored.split(SEPARATOR)
        assert len(expected) == len(bodies), (
            f"{message_type}: golden has {len(expected)} bodies, "
            f"captured {len(bodies)}"
        )
        for index, (want, got) in enumerate(zip(expected, bodies, strict=True)):
            if want != got:
                pytest.fail(
                    f"{message_type} body {index} drifted from golden:\n"
                    + _readable_diff(want, got)
                )


def test_no_orphan_golden_files(corpus: dict[str, list[str]]) -> None:
    """A golden file with no live publisher is stale and misleading."""
    if not GOLDEN_DIR.exists():
        pytest.skip("no golden corpus yet")
    stored = {p.stem for p in GOLDEN_DIR.glob("*.xml")}
    orphans = sorted(stored - set(corpus))
    assert not orphans, f"golden files with no publisher: {orphans}"
