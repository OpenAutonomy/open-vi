"""Per-interaction required fields, from the ASK 5.0a VI Volume §1.2.

Each numbered interaction in §1.2 carries a ``Table 1-NN`` listing the
messages it exchanges and, per message, the fields that interaction
requires:

    Message Name (Name:Type)        Required Fields (Name:Type)
    MA_FlightCommandMT: ...MT       WaypointFollowing: MA_WaypointControlType

followed by "Note: The fields above are required for this use case in
addition to what is specified in Autonomy Schema."

This is the oracle for the Execution axis in docs/FEATURES.md, the way
:mod:`spec_mms` (Table 1-38) is the oracle for the Sequence axis. The
distinction matters because almost every A-GRA element is ``[0..1]``,
so a message can satisfy the XSD and Table 1-38 while carrying none of
the substance its interaction needs — ``MA_FlightCapabilityStatus``
without ``AvailabilityReason`` is schema-valid and tells MA nothing
about why the capability went away.

Three things the tables themselves get wrong, recorded here rather
than worked around silently, because a parser that "fixed" them would
be hiding spec defects:

* Two rows pair a label with a type that is not its own —
  :data:`LABEL_TYPE_MISMATCHES`. The label is authoritative; it is what
  matches Table 1-38 and the surrounding prose.
* Tables 1-12 and 1-13 require four fields of
  ``MA_ControlAssignmentMT`` that its content model does not contain —
  :data:`FIELDS_NOT_IN_TYPE`. They belong to ``ControlStatus``, as
  their own type column ("ControlStatusCapabilityControlType") says.
* ``Table 1-18`` has a header row and no messages. "Route Plan Data
  Validation" composes the other three behaviours in its package
  rather than exchanging anything itself.

Enum constraints (a bare ``DEACTIVATE:`` cell, meaning the field above
must carry that value) are recorded per message, not per field: the
PDF text layer orders them unreliably relative to the field they
constrain, and Table 1-22 interleaves them.

The volume is not redistributed here; ``scripts/fetch-agra-spec.sh``
fetches it under digest. :func:`load` returns ``None`` when it is
absent so callers can skip rather than fail.
"""

from __future__ import annotations

import dataclasses
import functools
import pathlib
import re

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
VOLUME = (
    _REPO_ROOT / "schema" / "a-gra" / "ASK 5.0a Vehicle Interface Volume.pdf"
)

_HEADER = "Message Name (Name:Type) Required Fields (Name:Type)"
_END = "Note: The fields above are required for this use case"

# Page furniture interleaves the tables wherever one crosses a page.
_FURNITURE = re.compile(
    r"^\s*(Vehicle Interface Volume \(v\. 5\.0a\)|Page \d+|Vehicle|Interface"
    r"|Volume|Figure 1-\d+:.*)\s*$"
)
_CAPTION = re.compile(r"^Table (1-\d+): (.+?)\s*$", re.M)

# A cell anchor: "FieldName:" or "MessageLabelMT_2:".
_ANCHOR = re.compile(r"(?<![\w:])([A-Za-z_][A-Za-z0-9_]*):")
_IS_MESSAGE = re.compile(r"MT(_\d+)?$")
_INSTANCE_SUFFIX = re.compile(r"_\d+$")

# Every A-GRA type the Required Fields column names ends in Type, Enum
# or PET; the only exception across all 36 tables is the xs:int on
# MA_Fault's FaultCodeCount. Discriminating on the *type* token is what
# separates a field from a bare required value: "HSA_CSA:
# MA_HSA_CSA_Type" is a field whose name is upper case, and classifying
# on the name's case instead dropped it.
_IS_TYPE = re.compile(r"(Type|Enum|PET)$")
_XSD_PRIMITIVES = frozenset(
    {
        "int",
        "integer",
        "long",
        "short",
        "string",
        "boolean",
        "float",
        "double",
        "decimal",
        "dateTime",
        "date",
        "time",
        "duration",
        "anyURI",
        "base64Binary",
        "hexBinary",
    }
)
_IS_VALUE = re.compile(r"[A-Z][A-Z0-9_]*")

# Counts for v5.0a. A parse that lands anywhere else means the text
# layer changed, and checking a subset of the obligations while
# reporting success is worse than failing.
EXPECTED_TABLES = 36
EXPECTED_MESSAGES = 146
EXPECTED_FIELDS = 120
EXPECTED_ENUMS = 11

# Rows whose Required Fields column is the string "None" carry no
# obligation; they are kept as messages so the message count is the
# table's own, not a filtered one.

LABEL_TYPE_MISMATCHES = {
    # table: (label, the type the table prints beside it)
    "1-15": ("MA_FlightCapabilityStatusMT", "MA_FlightCommandStatusMT"),
    "1-24": (
        "MA_MissionPlanActivationStatusMT",
        "MA_MissionPlanActivationCommandMT",
    ),
}

# (table, message type, field) required of a type whose A-GRA content
# model has no such element. Not checkable, and not open-vi's defect.
FIELDS_NOT_IN_TYPE = frozenset(
    (table, "MA_ControlAssignmentMT", field)
    for table in ("1-12", "1-13")
    for field in (
        "SecondaryController",
        "AcceptedInterface",
        "CapabilityControl",
        "PrimaryController",
    )
)

EMPTY_TABLES = frozenset({"1-18"})

# Table 1-24 prints "MA_MissionPlanActivationStatusMT". Table 1-38 --
# the Minimum Message Set, which MA-L1-015 makes the compliance
# requirement -- lists "MissionPlanActivationStatus" out/Core and no
# MA_-prefixed variant. A-GRA declares both types, with identical
# paths for the two fields Table 1-24 requires, so the prefix is a
# third typo in a row that already pairs its label with the wrong
# type. Table 1-38 wins: it is what the VI is obliged to speak.
MMS_TYPE_OVERRIDES = {
    "MA_MissionPlanActivationStatusMT": "MissionPlanActivationStatusMT",
}


class SpecUnavailableError(RuntimeError):
    """The volume is present but §1.2's tables could not be read."""


@dataclasses.dataclass(frozen=True)
class RequiredField:
    """One ``Name: Type`` entry in a Required Fields cell."""

    name: str
    type_name: str


@dataclasses.dataclass(frozen=True)
class SpecMessage:
    """One row: a message instance and what the interaction requires."""

    label: str
    """As printed, including any ``_2`` instance suffix."""

    message_type: str
    """*label* with the instance suffix removed. Authoritative."""

    declared_type: str
    """The type column, which two rows get wrong."""

    required_fields: tuple[RequiredField, ...]
    required_values: tuple[str, ...]
    """Enum tokens the row requires, per message. See the module note."""

    @property
    def mms_type(self) -> str:
        """*message_type*, corrected against Table 1-38.

        See :data:`MMS_TYPE_OVERRIDES`. Equal to *message_type* for
        every row but one.
        """
        return MMS_TYPE_OVERRIDES.get(self.message_type, self.message_type)

    @property
    def element_name(self) -> str:
        """The global element name: :attr:`mms_type` without its suffix."""
        return re.sub(r"MT$", "", self.mms_type)


@dataclasses.dataclass(frozen=True)
class Interaction:
    """One ``Table 1-NN`` and its rows."""

    table: str
    caption: str
    messages: tuple[SpecMessage, ...]


def _volume_text() -> str:
    import pypdf  # imported lazily; only the conformance path needs it

    reader = pypdf.PdfReader(str(VOLUME))
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # pragma: no cover - malformed page
            pages.append("")
    return "\n".join(pages)


def _table_bodies(text: str) -> list[tuple[str, str, str]]:
    """``(table, caption, body)`` for each caption in the document body."""
    out = []
    for match in _CAPTION.finditer(text):
        caption = match.group(2).strip()
        if "...." in caption:  # table of contents, dot leaders
            continue
        start = match.end()
        end = text.find(_END, start)
        following = _CAPTION.search(text, start)
        if following and (end == -1 or following.start() < end):
            end = following.start()
        stop = end if end != -1 else len(text)
        out.append((match.group(1), caption, text[start:stop]))
    return out


def _flatten(body: str) -> str | None:
    """Table body as one line, or ``None`` if it has no column header."""
    lines = [
        line.strip()
        for line in body.splitlines()
        if line.strip() and not _FURNITURE.match(line)
    ]
    try:
        first = next(i for i, line in enumerate(lines) if _HEADER in line)
    except StopIteration:
        return None  # Tables 1-37 and 1-38 are not interaction tables
    rejoined: list[str] = []
    for line in lines[first + 1 :]:
        # A label too wide for the column splits mid-token:
        # "MA_MissionPlanActivationCommandStatusMT_" then "1:".
        if rejoined and rejoined[-1].endswith("_"):
            rejoined[-1] += line
        else:
            rejoined.append(line)
    return " ".join(rejoined)


def _parse_rows(flat: str) -> tuple[SpecMessage, ...]:
    anchors = list(_ANCHOR.finditer(flat))
    cells = [
        (
            match.group(1),
            flat[
                match.end() : (
                    anchors[i + 1].start()
                    if i + 1 < len(anchors)
                    else len(flat)
                )
            ].split(),
        )
        for i, match in enumerate(anchors)
    ]
    rows: list[dict] = []
    for name, tokens in cells:
        if _IS_MESSAGE.search(name):
            rows.append(
                {
                    "label": name,
                    "type": _INSTANCE_SUFFIX.sub("", name),
                    "declared": tokens[0] if tokens else "",
                    "fields": [],
                    "values": [],
                }
            )
            continue
        if not rows:  # pragma: no cover - a field before any message row
            continue
        typed = bool(
            tokens
            and (_IS_TYPE.search(tokens[0]) or tokens[0] in _XSD_PRIMITIVES)
        )
        if typed:
            rows[-1]["fields"].append(RequiredField(name, tokens[0]))
        elif _IS_VALUE.fullmatch(name):
            # A bare "CANCELED:" cell: the value the field above must
            # carry. Its text may run into a neighbouring cell (Table
            # 1-33 absorbs a diagram participant label), so only the
            # token itself is kept.
            rows[-1]["values"].append(name)
        # Anything else is neither: Table 1-33 prints the lifeline
        # label "Internal Terrain Request:" inside the table body.
    return tuple(
        SpecMessage(
            label=row["label"],
            message_type=row["type"],
            declared_type=row["declared"],
            required_fields=tuple(row["fields"]),
            required_values=tuple(row["values"]),
        )
        for row in rows
    )


@functools.lru_cache(maxsize=1)
def load() -> tuple[Interaction, ...] | None:
    """Every §1.2 interaction table, or ``None`` without the volume.

    Raises:
        SpecUnavailableError: the volume is present but the parse did
            not match the recorded counts, so it cannot be trusted as
            the compliance oracle.
    """
    if not VOLUME.is_file():
        return None
    text = _volume_text()
    interactions = []
    for table, caption, body in _table_bodies(text):
        flat = _flatten(body)
        if flat is None:
            continue
        interactions.append(Interaction(table, caption, _parse_rows(flat)))

    messages = sum(len(i.messages) for i in interactions)
    fields = sum(
        len(m.required_fields) for i in interactions for m in i.messages
    )
    values = sum(
        len(m.required_values) for i in interactions for m in i.messages
    )
    counted = {
        "tables": (len(interactions), EXPECTED_TABLES),
        "messages": (messages, EXPECTED_MESSAGES),
        "fields": (fields, EXPECTED_FIELDS),
        "enum values": (values, EXPECTED_ENUMS),
    }
    wrong = [
        f"{what}: parsed {got}, expected {want}"
        for what, (got, want) in counted.items()
        if got != want
    ]
    if wrong:
        raise SpecUnavailableError(
            "the volume's §1.2 text layer has changed: " + "; ".join(wrong)
        )
    return tuple(interactions)


def by_table() -> dict[str, Interaction]:
    """``{table id: interaction}``, or empty without the volume."""
    loaded = load()
    return {} if loaded is None else {i.table: i for i in loaded}


def required_fields() -> tuple[tuple[str, SpecMessage, RequiredField], ...]:
    """Flat ``(table, message, field)`` triples across every table."""
    loaded = load()
    if loaded is None:
        return ()
    return tuple(
        (interaction.table, message, field)
        for interaction in loaded
        for message in interaction.messages
        for field in message.required_fields
    )
