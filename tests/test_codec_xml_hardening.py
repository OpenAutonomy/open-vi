"""The inbound parse boundary, against hostile XML.

SECURITY.md puts "a hang, crash, or unbounded loop reachable from a
peer's XML or STOMP frames" in scope, on a bus it also states is
unauthenticated. Every inbound body reaches the codec through
``parse_xml``, so that function is where the posture is set and this
is where it is held.

These are not hypothetical shapes. The expansion case below was
measured against the stdlib parser before the fix: a ~310 byte
document became ~3 MB with no error raised, because expat's
amplification guard does not arm until a document is already large.
"""

from __future__ import annotations

import pytest
from defusedxml.common import DefusedXmlException

from open_vi.codec.ns import NS
from open_vi.codec.xmlutil import parse_xml


def _nested_entities(levels: int) -> str:
    """A billion-laughs document with *levels* of nesting."""
    names = "abcdefgh"[:levels]
    decls = [f'<!ENTITY {names[0]} "{"a" * 30}">']
    for index in range(1, levels):
        body = "".join(f"&{names[index - 1]};" for _ in range(10))
        decls.append(f'<!ENTITY {names[index]} "{body}">')
    return (
        '<?xml version="1.0"?>'
        f"<!DOCTYPE l [{''.join(decls)}]>"
        f"<l>&{names[-1]};</l>"
    )


@pytest.mark.parametrize("levels", [2, 4, 6])
def test_entity_expansion_is_refused(levels: int) -> None:
    """Nested entity declarations are refused, not expanded.

    Parameterised across depths because the stdlib failure was
    depth-dependent: shallow documents stayed under expat's guard and
    expanded silently, which is the case a single deep payload would
    have missed.
    """
    payload = _nested_entities(levels)
    assert len(payload) < 1024, "payload should be small; that is the point"
    with pytest.raises(DefusedXmlException):
        parse_xml(payload)


def test_external_entity_is_refused() -> None:
    """A SYSTEM entity must not be resolved, nor silently dropped."""
    payload = (
        '<?xml version="1.0"?>'
        '<!DOCTYPE f [<!ENTITY x SYSTEM "file:///etc/passwd">]>'
        "<r>&x;</r>"
    )
    with pytest.raises(DefusedXmlException):
        parse_xml(payload)


def test_defused_errors_are_value_errors() -> None:
    """The refusal is a ValueError subclass.

    Handlers treat a parse failure as a dropped message; a refusal
    that escaped that contract would become an unhandled fault on the
    Isolator thread rather than a discarded frame.
    """
    with pytest.raises(ValueError):
        parse_xml(_nested_entities(4))


def test_malformed_xml_still_raises_parse_error() -> None:
    from xml.etree.ElementTree import ParseError

    with pytest.raises(ParseError):
        parse_xml(b"<unclosed>")


def test_wellformed_uci_xml_still_parses() -> None:
    """The guard must not cost the codec its ordinary input."""
    body = (
        f'<ServiceStatus xmlns="{NS}">'
        "<MessageData><ServiceID><UUID>00000000000000000000000000000001"
        "</UUID></ServiceID></MessageData>"
        "</ServiceStatus>"
    )
    root = parse_xml(body)
    assert root.tag == f"{{{NS}}}ServiceStatus"
    assert root.find(f"{{{NS}}}MessageData") is not None


def test_doctype_without_entities_is_tolerated() -> None:
    """Only entity declarations are the hazard, not a bare DOCTYPE.

    Pinned so a future tightening to ``forbid_dtd`` is a deliberate
    decision with a failing test behind it, rather than a quiet
    change in what peers can send.
    """
    assert parse_xml('<?xml version="1.0"?><!DOCTYPE r><r/>').tag == "r"
