"""The volume's obligations, against the schema it normatively cites.

:mod:`spec_interactions` reads field *names* out of a PDF. This checks
each one is real: that A-GRA declares the message type, and that the
type's content model actually contains an element by that name. It is
the semantic half of pinning the parse — the counts in
``test_spec_interactions`` prove nothing was lost, these prove nothing
was invented.

It also settles the one place the volume contradicts its own schema,
by evidence rather than by assertion: the four fields Tables 1-12 and
1-13 require of ``MA_ControlAssignment`` do not exist in that type and
do exist in ``ControlStatus``.
"""

from __future__ import annotations

import pytest

import agra_schema
import spec_interactions

# 120 obligations less the 8 in FIELDS_NOT_IN_TYPE.
EXPECTED_RESOLVED = 112


@pytest.fixture(scope="module")
def obligations():
    fields = spec_interactions.required_fields()
    if not fields:
        pytest.skip(
            "no Vehicle Interface Volume: run ./scripts/fetch-agra-spec.sh"
        )
    return fields


@pytest.fixture(scope="module", autouse=True)
def _schema():
    if agra_schema.load() is None:
        pytest.skip("no A-GRA schema: run ./scripts/fetch-agra-schema.sh")


def test_every_message_type_is_declared_by_the_schema(obligations) -> None:
    """A row naming a type A-GRA does not declare is a misparse."""
    undeclared = sorted(
        {
            message.mms_type
            for interaction in spec_interactions.load()
            for message in interaction.messages
            if not agra_schema.has_type(message.mms_type)
        }
    )
    assert not undeclared, f"not A-GRA types: {undeclared}"


def test_every_obligation_resolves_or_is_recorded(obligations) -> None:
    """Each required field is an element of its message, or a known defect."""
    unresolved = {
        (table, message.mms_type, field.name)
        for table, message, field in obligations
        if agra_schema.element_path(message.mms_type, field.name) is None
    }
    recorded = set(spec_interactions.FIELDS_NOT_IN_TYPE)
    assert unresolved == recorded, (
        "unresolved obligations changed:\n"
        f"  newly unresolved: {sorted(unresolved - recorded)}\n"
        f"  now resolving: {sorted(recorded - unresolved)}"
    )
    assert len(obligations) - len(unresolved) == EXPECTED_RESOLVED


def test_the_control_assignment_fields_live_on_control_status() -> None:
    """Why :data:`FIELDS_NOT_IN_TYPE` is the volume's defect, not ours.

    Tables 1-12 and 1-13 require these of ``MA_ControlAssignmentMT``,
    whose content model is ``MessageData/ControlAssignment`` ->
    ``MA_ControlAssignmentType``, extending
    ``MA_ControlDefinitionBaseType``: ``ControlChoiceType``,
    ``Controller``, ``Controllee``. Nothing else. Their own type column
    ("ControlStatusCapabilityControlType") names where they belong, and
    §1.2.2.8's prose repeats the misattribution.

    open-vi emits them on ``ControlStatus``. If a later volume moves
    the rows, this and the registry both fail and the exemption comes
    off together.
    """
    for _, message_type, field in sorted(spec_interactions.FIELDS_NOT_IN_TYPE):
        assert agra_schema.element_path(message_type, field) is None, (
            f"{field} now resolves under {message_type}"
        )
        assert agra_schema.element_path("ControlStatusMT", field), (
            f"{field} does not resolve under ControlStatusMT either"
        )


def test_resolution_descends_through_an_extension_base() -> None:
    """The walk must cross ``xs:extension``, or it misses inherited fields.

    ``MA_ControlRequestStatusMDT`` declares
    ``ApprovalRequestProcessingState`` itself and inherits
    ``RequestProcessingState`` from ``RequestStatusBaseType``. A walker
    that stopped at the derived type would resolve one and not the
    other — and the pair is exactly where open-vi fills the wrong one.
    """
    own = agra_schema.element_path(
        "MA_ControlRequestStatusMT", "ApprovalRequestProcessingStateReason"
    )
    inherited = agra_schema.element_path(
        "MA_ControlRequestStatusMT", "RequestProcessingStateReason"
    )
    assert own == ("MessageData", "ApprovalRequestProcessingStateReason")
    assert inherited == ("MessageData", "RequestProcessingStateReason")


def test_paths_start_inside_the_message_not_at_its_root() -> None:
    """A path is relative to the MT, so it is usable against emitted XML."""
    path = agra_schema.element_path("MA_PositionReportDetailedMT", "Kinematics")
    assert path == ("MessageData", "PositionReportData", "Kinematics")
