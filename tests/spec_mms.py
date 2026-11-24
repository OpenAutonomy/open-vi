"""Table 1-38 (VI MMS) from the ASK 5.0a Vehicle Interface Volume.

MA-L1-015 makes this table the compliance requirement: "A Level 1 VI
interface shall support the VI Interface Minimum Message Set defined
in this architecture for signals that own a 'VI = 1' tagged value."
The volume states the Direction column is "relative to the VI
interface" and the MUC column names the Mission Use Case a message is
required for.

That makes this table the oracle for both the FEATURES claim and the
implementation. Inferring direction from the code instead is how
``SubsystemStatus`` and ``MA_MissionPlanActivationCommand`` previously
got documented backwards.

The volume is not redistributed here; ``scripts/fetch-agra-spec.sh``
fetches it under digest. ``load()`` returns ``None`` when it is absent
so callers can skip rather than fail.
"""

from __future__ import annotations

import functools
import pathlib
import re

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
VOLUME = (
    _REPO_ROOT / "schema" / "a-gra" / "ASK 5.0a Vehicle Interface Volume.pdf"
)

# "MA_FlightCommandMT VI in Core" — the Message Type column wraps
# unpredictably in the PDF text layer, so anchor on the message name
# and read the two columns after the "VI" interface marker.
_ROW = re.compile(
    r"(?P<name>[A-Za-z_][A-Za-z0-9_]*)MT\s+VI\s+"
    r"(?P<direction>inout|in|out)\s+"
    r"(?P<muc>Core|[A-Z][A-Za-z0-9 \-]*?)\s*(?=\n|$)",
    re.M,
)

# Table 1-38 has this many rows in v5.0a. A parse that finds a
# different number means the text layer changed and the regex needs
# revisiting — better to fail than to silently check a subset.
EXPECTED_ROWS = 49


class SpecUnavailableError(RuntimeError):
    """The volume is present but Table 1-38 could not be read from it."""


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


@functools.lru_cache(maxsize=1)
def load() -> dict[str, tuple[str, str]] | None:
    """``{message type: (direction, MUC)}``, or ``None`` without the volume.

    Raises:
        SpecUnavailableError: the volume is present but the table did
            not parse to :data:`EXPECTED_ROWS` rows, so the result
            cannot be trusted as the compliance oracle.
    """
    if not VOLUME.is_file():
        return None
    text = _volume_text()
    try:
        start = text.rindex("Table 1-38: VI MMS")
    except ValueError as exc:
        raise SpecUnavailableError(
            "no 'Table 1-38: VI MMS' heading in the volume text layer"
        ) from exc
    end = text.find("1.3.2", start)
    segment = text[start : end if end != -1 else len(text)]

    rows: dict[str, tuple[str, str]] = {}
    for match in _ROW.finditer(segment):
        rows[match.group("name")] = (
            match.group("direction"),
            match.group("muc").strip(),
        )
    if len(rows) != EXPECTED_ROWS:
        raise SpecUnavailableError(
            f"parsed {len(rows)} rows from Table 1-38, expected "
            f"{EXPECTED_ROWS}; the PDF text layer has changed"
        )
    return rows


def core_message_types() -> set[str]:
    """Message types the Core MUC requires, or empty without the volume."""
    rows = load()
    if rows is None:
        return set()
    return {mt for mt, (_, muc) in rows.items() if muc == "Core"}
