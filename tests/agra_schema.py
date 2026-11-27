"""Resolve element paths in the A-GRA 5.0a content model.

:mod:`spec_interactions` yields obligations as ``(message type, field
name)``. To check one against emitted XML you need where that field
sits inside that message — the volume's tables give a name and a type,
never a path.

This walks the fetched XSD to find it, descending through the three
things A-GRA uses that a naive scan misses: ``xs:extension`` bases
(``MA_ControlRequestStatusMDT`` gets ``RequestID`` and
``RequestProcessingState`` from ``RequestStatusBaseType``), named
``xs:group`` references, and inline anonymous ``xs:complexType``
declarations.

The schema is fetched, not vendored — ``scripts/fetch-agra-schema.sh``,
pinned in ``scripts/agra-schema.sha256``. :func:`load` returns ``None``
without it so callers skip rather than fail.
"""

from __future__ import annotations

import collections
import functools
import os
import pathlib
from xml.etree import ElementTree as ET

XS = "{http://www.w3.org/2001/XMLSchema}"
XSD_ENV = "UCI_XSD"

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FETCHED = (
    _REPO_ROOT / "schema" / "a-gra" / "A-GRA_MessageDefinitions_v5_0_a.xsd"
)

# Containers whose children continue the same content model.
_TRANSPARENT = frozenset(
    {
        f"{XS}sequence",
        f"{XS}choice",
        f"{XS}all",
        f"{XS}complexContent",
        f"{XS}extension",
        f"{XS}restriction",
    }
)

# A-GRA nests about six levels below MessageData at its deepest
# (MA_ControlAssignment's controller identity, ControlStatus's
# capability control). Ten bounds the search without truncating a real
# path; a field that needs more is reported unresolvable rather than
# found slowly.
MAX_DEPTH = 10


def _local(name: str | None) -> str:
    return name.split(":")[-1] if name else ""


def _xsd_path() -> pathlib.Path | None:
    """``UCI_XSD`` if set, else the fetched catalog, else ``None``."""
    raw = os.environ.get(XSD_ENV, "").strip()
    if raw:
        path = pathlib.Path(raw).expanduser()
        return path if path.is_file() else None
    return _FETCHED if _FETCHED.is_file() else None


class _Index:
    """Global elements, named complexTypes and named groups."""

    def __init__(self, root: ET.Element) -> None:
        self.elements: dict[str, ET.Element] = {}
        self.types: dict[str, ET.Element] = {}
        self.groups: dict[str, ET.Element] = {}
        for child in root:
            name = child.get("name")
            if not name:
                continue
            if child.tag == f"{XS}element":
                self.elements[name] = child
            elif child.tag == f"{XS}complexType":
                self.types[name] = child
            elif child.tag == f"{XS}group":
                self.groups[name] = child

    def body(self, decl: ET.Element) -> ET.Element | None:
        """The complexType for an element declaration, named or inline."""
        named = _local(decl.get("type"))
        if named:
            return self.types.get(named)
        for kid in decl:
            if kid.tag == f"{XS}complexType":
                return kid
        return None

    def children(self, node: ET.Element) -> list[ET.Element]:
        """Element declarations directly inside a complexType node."""
        out: list[ET.Element] = []
        stack = [node]
        seen: set[str] = set()
        while stack:
            for kid in stack.pop():
                if kid.tag == f"{XS}element":
                    if kid.get("name"):
                        out.append(kid)
                    else:
                        ref = _local(kid.get("ref"))
                        if ref in self.elements:
                            out.append(self.elements[ref])
                elif kid.tag in _TRANSPARENT:
                    base = _local(kid.get("base"))
                    if base in self.types:
                        stack.append(self.types[base])
                    stack.append(kid)
                elif kid.tag == f"{XS}group":
                    ref = _local(kid.get("ref"))
                    if ref in self.groups and ref not in seen:
                        seen.add(ref)
                        stack.append(self.groups[ref])
        return out


@functools.lru_cache(maxsize=1)
def load() -> _Index | None:
    """Index the fetched schema, or ``None`` when it is absent."""
    path = _xsd_path()
    if path is None:
        return None
    return _Index(ET.parse(path).getroot())


def has_type(message_type: str) -> bool:
    """True when the schema declares *message_type* as a complexType."""
    index = load()
    return index is not None and message_type in index.types


@functools.lru_cache(maxsize=4096)
def element_path(message_type: str, field: str) -> tuple[str, ...] | None:
    """Shortest element path from *message_type* down to *field*.

    The ``MessageData`` subtree is searched first. A name can occur in
    both the payload and the envelope — ``MA_Fault`` has a
    ``ServiceID`` under each — and the interaction tables describe
    payload content, so the shallowest match overall can be the wrong
    element. Table 1-4's nine required fields are exactly the members
    of ``MA_SubsystemFaultType``, ``ServiceID`` among them, while
    ``MessageHeader/ServiceID`` is a shorter path to a different
    field.

    Returns ``None`` when the schema is absent, the type is unknown,
    or the content model has no such element — the last being a real
    answer, not a failure: Tables 1-12 and 1-13 require fields of
    ``MA_ControlAssignmentMT`` that it cannot carry.
    """
    index = load()
    if index is None:
        return None
    root = index.types.get(message_type)
    if root is None:
        return None
    for decl in index.children(root):
        if (decl.get("name") or "") != "MessageData":
            continue
        body = index.body(decl)
        if body is not None:
            under = _search(index, body, field, message_type)
            if under is not None:
                return ("MessageData", *under)
        break
    return _search(index, root, field, message_type)


def _search(
    index: _Index, root: ET.Element, field: str, type_name: str
) -> tuple[str, ...] | None:
    """Breadth-first walk for *field* beneath the *root* content model."""
    queue: collections.deque[tuple[ET.Element, tuple[str, ...]]] = (
        collections.deque([(root, ())])
    )
    seen = {type_name}
    while queue:
        node, path = queue.popleft()
        if len(path) >= MAX_DEPTH:
            continue
        for decl in index.children(node):
            name = decl.get("name") or _local(decl.get("ref"))
            if name == field:
                return path + (name,)
            body = index.body(decl)
            if body is None:
                continue
            # Key on the type so a recursive model terminates; fall
            # back to the path for inline anonymous types, which have
            # no name to collide on.
            key = _local(decl.get("type")) or "/".join(path + (name,))
            if key in seen:
                continue
            seen.add(key)
            queue.append((body, path + (name,)))
    return None
