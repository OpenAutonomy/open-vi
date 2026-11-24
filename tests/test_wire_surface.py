"""The documented message set must match the implemented one.

FEATURES §1.3.1 is the compliance claim; this asserts it against the
code. Direction is checked by what the code actually does — a type is
inbound if a handler subscribes to it, and outbound if some module
calls ``bus.publish`` with it — not by whether its name appears
somewhere in the tree, which is true of every type either way.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

from open_vi.codec import mts
from open_vi.isolator.handlers import collect_inbound_mts, default_handlers

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "open_vi"
_FEATURES = pathlib.Path(__file__).resolve().parents[1] / "docs" / "FEATURES.md"
_ROW = re.compile(r"^\| (\w+) \| (in|out|inout) \| (Supported|Not supported) ")


def _mt_constants() -> dict[str, str]:
    return {n: getattr(mts, n) for n in dir(mts) if n.startswith("MT_")}


def published_message_types() -> set[str]:
    """Message types reached by a real ``bus.publish`` call site."""
    const = _mt_constants()
    found: set[str] = set()
    for path in _SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call):
                continue
            func = node.func
            if not (isinstance(func, ast.Attribute) and func.attr == "publish"):
                continue
            if not node.args:
                continue
            arg = node.args[0]
            name = None
            if isinstance(arg, ast.Name):
                name = const.get(arg.id)
            elif isinstance(arg, ast.Attribute):
                name = const.get(arg.attr)
            elif isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                name = arg.value
            if name:
                found.add(name)
    return found


def documented_rows() -> dict[str, tuple[str, str]]:
    """``{message type: (direction, support)}`` from FEATURES §1.3.1."""
    rows: dict[str, tuple[str, str]] = {}
    for line in _FEATURES.read_text().splitlines():
        match = _ROW.match(line)
        if match:
            rows[match.group(1)] = (match.group(2), match.group(3))
    return rows


@pytest.fixture(scope="module")
def rows() -> dict[str, tuple[str, str]]:
    parsed = documented_rows()
    assert len(parsed) >= 49, f"only parsed {len(parsed)} MMS rows"
    return parsed


def test_documented_inbound_is_subscribed(
    rows: dict[str, tuple[str, str]],
) -> None:
    documented = {
        mt
        for mt, (direction, support) in rows.items()
        if direction in ("in", "inout") and support == "Supported"
    }
    assert documented == set(collect_inbound_mts(default_handlers()))


def test_documented_outbound_is_published(
    rows: dict[str, tuple[str, str]],
) -> None:
    """An ``out`` claim needs a publish site, not just a constant."""
    documented = {
        mt
        for mt, (direction, support) in rows.items()
        if direction in ("out", "inout") and support == "Supported"
    }
    published = published_message_types()
    assert not documented - published, (
        f"documented outbound with no publish site: "
        f"{sorted(documented - published)}"
    )
    assert not published - documented, (
        f"published but not documented outbound: "
        f"{sorted(published - documented)}"
    )


def test_unsupported_rows_are_not_implemented(
    rows: dict[str, tuple[str, str]],
) -> None:
    """A Not supported row must have neither a handler nor a publisher."""
    unsupported = {
        mt for mt, (_, support) in rows.items() if support == "Not supported"
    }
    inbound = set(collect_inbound_mts(default_handlers()))
    published = published_message_types()
    for mt in sorted(unsupported):
        assert mt not in inbound, f"{mt} is Not supported but subscribed"
        assert mt not in published, f"{mt} is Not supported but published"


def test_every_mt_constant_is_documented(
    rows: dict[str, tuple[str, str]],
) -> None:
    """A message type in ``mts.py`` with no FEATURES row is undocumented."""
    undocumented = sorted(set(_mt_constants().values()) - set(rows))
    assert not undocumented, (
        f"MT constants absent from FEATURES: {undocumented}"
    )
