"""Structural invariants every outbound UCI message must satisfy.

These are the schema-shaped rules the codec already claims in
docs/CODEC.md, asserted against the real publish path. They are not a
substitute for XSD validation — see test_wire_xsd.py — but they hold
with no schema catalog present, and they catch the class of defect the
missing XSD leaves open: a message that is well-formed XML and passes
every unit test while carrying a wrong header, a mis-shaped identifier,
or a stale schema version.
"""

from __future__ import annotations

import re
from xml.etree import ElementTree as ET

import pytest

from open_vi.codec.ns import NS, SCHEMA_VERSION
from wire_helpers import FROZEN_TIME, capture_corpus

_UUID_RE = re.compile(r"^[0-9a-f]{32}$")
_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z$")


@pytest.fixture(scope="module")
def corpus() -> dict[str, list[str]]:
    mp = pytest.MonkeyPatch()
    try:
        return capture_corpus(mp)
    finally:
        mp.undo()


def _bodies(corpus: dict[str, list[str]]) -> list[tuple[str, str]]:
    return [(mt, b) for mt, bodies in corpus.items() for b in bodies]


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def test_corpus_is_not_empty(corpus: dict[str, list[str]]) -> None:
    """Guard against the capture silently publishing nothing."""
    assert len(corpus) >= 36
    assert len(_bodies(corpus)) >= 90


def test_every_body_is_well_formed(corpus: dict[str, list[str]]) -> None:
    for mt, body in _bodies(corpus):
        try:
            ET.fromstring(body)
        except ET.ParseError as exc:  # pragma: no cover - failure path
            pytest.fail(f"{mt} is not well-formed: {exc}")


def test_xml_declaration_and_default_namespace(
    corpus: dict[str, list[str]],
) -> None:
    """CAL expects the OAM default xmlns and no ``uci:`` prefix."""
    for mt, body in _bodies(corpus):
        assert body.startswith("<?xml version="), mt
        assert f'xmlns="{NS}"' in body, mt
        # No ``uci:`` *namespace prefix* on tags or attributes. The
        # ``uci://`` URI scheme inside FileLocation/Address is a
        # different thing and is legitimate.
        assert "<uci:" not in body, mt
        assert "</uci:" not in body, mt
        assert "xmlns:uci" not in body, mt
        assert ET.fromstring(body).tag.startswith(f"{{{NS}}}"), mt


def test_envelope_child_order(corpus: dict[str, list[str]]) -> None:
    """SecurityInformation, MessageHeader, optional ObjectState, MessageData."""
    for mt, body in _bodies(corpus):
        kids = [_local(c.tag) for c in ET.fromstring(body)]
        assert kids[0] == "SecurityInformation", f"{mt}: {kids}"
        assert kids[1] == "MessageHeader", f"{mt}: {kids}"
        assert kids[-1] == "MessageData", f"{mt}: {kids}"
        assert set(kids[2:-1]) <= {"ObjectState"}, f"{mt}: {kids}"


def test_message_header_shape(corpus: dict[str, list[str]]) -> None:
    for mt, body in _bodies(corpus):
        header = ET.fromstring(body).find(f"{{{NS}}}MessageHeader")
        assert header is not None, mt
        kids = [_local(c.tag) for c in header]
        assert kids == [
            "SystemID",
            "Timestamp",
            "SchemaVersion",
            "Mode",
        ], f"{mt}: {kids}"


def test_schema_version_is_the_codec_constant(
    corpus: dict[str, list[str]],
) -> None:
    """Pins the concrete value that goes out on the wire.

    Nothing else in the suite asserts it, so a wrong
    ``SCHEMA_VERSION`` — from a bad edit or a stale ``.pyc`` — would
    otherwise ship in every message with the suite still green.
    """
    assert SCHEMA_VERSION == "005.0a"
    for mt, body in _bodies(corpus):
        found = {
            e.text for e in ET.fromstring(body).iter(f"{{{NS}}}SchemaVersion")
        }
        assert found == {SCHEMA_VERSION}, f"{mt}: {found}"


def test_mode_is_consistent(corpus: dict[str, list[str]]) -> None:
    for mt, body in _bodies(corpus):
        found = {e.text for e in ET.fromstring(body).iter(f"{{{NS}}}Mode")}
        assert found == {"SIMULATION"}, f"{mt}: {found}"


def test_timestamps_are_uci_format(corpus: dict[str, list[str]]) -> None:
    """Millisecond precision with a literal Z, per ``utc_now``."""
    for mt, body in _bodies(corpus):
        stamps = [
            e.text for e in ET.fromstring(body).iter(f"{{{NS}}}Timestamp")
        ]
        assert stamps, mt
        for stamp in stamps:
            assert stamp is not None and _TIMESTAMP_RE.match(stamp), (
                f"{mt}: {stamp!r}"
            )
            assert stamp == FROZEN_TIME, f"{mt}: {stamp!r}"


def test_uuids_are_bare_32_hex(corpus: dict[str, list[str]]) -> None:
    """UCI UUIDs are undashed lowercase hex; a dashed one is a bug."""
    seen = 0
    for mt, body in _bodies(corpus):
        for node in ET.fromstring(body).iter(f"{{{NS}}}UUID"):
            text = (node.text or "").strip()
            assert _UUID_RE.match(text), f"{mt}: {text!r}"
            seen += 1
    assert seen > 100


def test_security_information_is_classified_u(
    corpus: dict[str, list[str]],
) -> None:
    for mt, body in _bodies(corpus):
        sec = ET.fromstring(body).find(f"{{{NS}}}SecurityInformation")
        assert sec is not None, mt
        classification = sec.find(f"{{{NS}}}Classification")
        assert classification is not None and classification.text == "U", mt


def test_no_empty_text_elements(corpus: dict[str, list[str]]) -> None:
    """A leaf with empty text is a builder that dropped a value."""
    offenders = []
    for mt, body in _bodies(corpus):
        for node in ET.fromstring(body).iter():
            if len(node) == 0 and node.text is not None:
                if node.text.strip() == "":
                    offenders.append(f"{mt}/{_local(node.tag)}")
    assert not offenders, offenders
