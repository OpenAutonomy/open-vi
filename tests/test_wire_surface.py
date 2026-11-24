"""The documented and implemented message sets, against the spec.

Table 1-38 of the ASK 5.0a Vehicle Interface Volume is the compliance
oracle: MA-L1-015 requires a Level 1 VI to support the Minimum Message
Set, and the volume states its Direction column is "relative to the VI
interface". So direction is dictated, not a judgement call.

An earlier version of this module asserted FEATURES against the
implementation. That is the wrong way round — it forces the
documentation to match whatever the code does, and it is how
``SubsystemStatus`` and ``MA_MissionPlanActivationCommand`` came to be
documented backwards. The spec is the oracle; FEATURES mirrors it, and
the code is measured against it.

The volume is not redistributed here. ``scripts/fetch-agra-spec.sh``
fetches it under digest; the spec-based tests skip without it, and the
internal-consistency tests still run.
"""

from __future__ import annotations

import ast
import pathlib
import re

import pytest

import spec_mms
from open_vi.codec import mts
from open_vi.isolator.handlers import collect_inbound_mts, default_handlers

_SRC = pathlib.Path(__file__).resolve().parents[1] / "src" / "open_vi"
_FEATURES = pathlib.Path(__file__).resolve().parents[1] / "docs" / "FEATURES.md"
_ROW = re.compile(r"^\| (\w+) \| (in|out|inout) \| (Supported|Not supported) ")

# Directions Table 1-38 requires that open-vi does not yet implement.
# Each is a real gap, recorded on the matching FEATURES row:
#
#   MA_MissionPlanActivationCommand out — §1.2.5.6 VI Deactivate Route
#   requires VI to send one with DEACTIVATED on abort. open-vi emits
#   MissionPlanActivationStatus instead.
#
#   SubsystemStatus in — §1.2.6.1 makes the inbound leg the Flight
#   Autonomy component heartbeat, which open-vi takes over PlatformPort
#   (PX4 SYS_STATUS) rather than as inbound UCI. Arguably satisfied
#   off-bus rather than missing, which is why it is listed separately
#   from a plain omission.
UNIMPLEMENTED_DIRECTIONS = {
    ("MA_MissionPlanActivationCommand", "out"),
    ("SubsystemStatus", "in"),
}


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


@pytest.fixture(scope="module")
def spec() -> dict[str, tuple[str, str]]:
    table = spec_mms.load()
    if table is None:
        pytest.skip(
            "no Vehicle Interface Volume: run ./scripts/fetch-agra-spec.sh"
        )
    return table


# --- FEATURES against the spec ------------------------------------------


def test_features_covers_the_whole_mms(spec, rows) -> None:
    """Every message Table 1-38 lists must appear in §1.3.1."""
    assert not sorted(set(spec) - set(rows)), (
        f"absent from FEATURES: {sorted(set(spec) - set(rows))}"
    )


def test_features_claims_no_message_outside_the_mms(spec, rows) -> None:
    assert not sorted(set(rows) - set(spec)), (
        f"in FEATURES but not Table 1-38: {sorted(set(rows) - set(spec))}"
    )


def test_features_directions_match_the_spec(spec, rows) -> None:
    """Direction is dictated by Table 1-38, never inferred from the code."""
    wrong = [
        f"{mt}: spec={direction} FEATURES={rows[mt][0]}"
        for mt, (direction, _) in sorted(spec.items())
        if rows[mt][0] != direction
    ]
    assert not wrong, "direction disagrees with Table 1-38:\n" + "\n".join(
        wrong
    )


# --- the implementation against the spec --------------------------------


def _declared_unsupported() -> set[str]:
    """Message types FEATURES itself marks Not supported.

    Exempt from the implemented-checks below, because
    ``test_unsupported_rows_are_not_implemented`` asserts the
    complement: that they really are absent from the code.
    """
    return {
        mt
        for mt, (_, support) in documented_rows().items()
        if support == "Not supported"
    }


def test_spec_inbound_is_subscribed(spec) -> None:
    """Every Core inbound message in Table 1-38 has a handler."""
    required = {
        mt
        for mt, (direction, muc) in spec.items()
        if direction in ("in", "inout") and muc == "Core"
    }
    subscribed = set(collect_inbound_mts(default_handlers()))
    exempt = _declared_unsupported()
    missing = sorted(
        mt
        for mt in required - subscribed
        if (mt, "in") not in UNIMPLEMENTED_DIRECTIONS and mt not in exempt
    )
    assert not missing, f"Core inbound not subscribed: {missing}"


def test_spec_outbound_is_published(spec) -> None:
    """Every Core outbound message in Table 1-38 has a publish site."""
    required = {
        mt
        for mt, (direction, muc) in spec.items()
        if direction in ("out", "inout") and muc == "Core"
    }
    published = published_message_types()
    exempt = _declared_unsupported()
    missing = sorted(
        mt
        for mt in required - published
        if (mt, "out") not in UNIMPLEMENTED_DIRECTIONS and mt not in exempt
    )
    assert not missing, f"Core outbound not published: {missing}"


def test_nothing_published_outside_the_mms(spec) -> None:
    extra = sorted(published_message_types() - set(spec))
    assert not extra, f"published but not in Table 1-38: {extra}"


def test_unimplemented_directions_are_still_unimplemented(spec) -> None:
    """Keeps the gap registry from outliving the gaps.

    A direction that has since been implemented must come off the list,
    or the suite stops noticing the next one.
    """
    subscribed = set(collect_inbound_mts(default_handlers()))
    published = published_message_types()
    fixed = []
    for mt, direction in sorted(UNIMPLEMENTED_DIRECTIONS):
        if direction == "in" and mt in subscribed:
            fixed.append(f"{mt} in")
        if direction == "out" and mt in published:
            fixed.append(f"{mt} out")
    assert not fixed, (
        f"now implemented; drop from UNIMPLEMENTED_DIRECTIONS: {fixed}"
    )


# --- internal consistency, no spec needed ------------------------------


def test_unsupported_rows_are_not_implemented(rows) -> None:
    """A Not supported row must have neither a handler nor a publisher."""
    unsupported = {
        mt for mt, (_, support) in rows.items() if support == "Not supported"
    }
    inbound = set(collect_inbound_mts(default_handlers()))
    published = published_message_types()
    for mt in sorted(unsupported):
        assert mt not in inbound, f"{mt} is Not supported but subscribed"
        assert mt not in published, f"{mt} is Not supported but published"


def test_every_mt_constant_is_documented(rows) -> None:
    """A message type in ``mts.py`` with no FEATURES row is undocumented."""
    undocumented = sorted(set(_mt_constants().values()) - set(rows))
    assert not undocumented, (
        f"MT constants absent from FEATURES: {undocumented}"
    )


# Core messages FEATURES declares Not supported. Table 1-38 requires
# them for Core, so each is an open compliance gap, not a scoping
# choice — unlike the two MA Terrain Data rows, which Table 1-38 scopes
# to another MUC.
CORE_GAPS = {"MA_ActionStatus"}


def test_core_gaps_are_exactly_as_recorded(spec, rows) -> None:
    """The set of Core messages we admit we do not support cannot drift."""
    declared = {
        mt
        for mt, (_, support) in rows.items()
        if support == "Not supported" and spec.get(mt, ("", ""))[1] == "Core"
    }
    assert declared == CORE_GAPS, (
        f"Core compliance gaps changed: {sorted(declared)} "
        f"vs recorded {sorted(CORE_GAPS)}"
    )
