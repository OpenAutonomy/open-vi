"""What open-vi emits, against what each interaction requires.

The Execution axis in docs/FEATURES.md claims Isolator applies the
product effect of an interaction, not merely that it answers. Nothing
checked that. Table 1-38 checks *which* messages cross the interface
and the XSD checks each is well formed; neither can say a message
carried the substance its use case needed, because almost every A-GRA
element is ``[0..1]``.

:mod:`spec_interactions` reads those obligations and
:mod:`agra_schema` locates each one in its message. This module
accounts for every one of them, in exactly one of four buckets, and
asserts each bucket in both directions so none can quietly change
size:

``EMITTED``
    The field is in the published corpus. 64 entries, checked.

``CONDITIONAL``
    The codec emits it only when the domain supplies the data, and the
    corpus captures one nominal state. A scan alone would call these
    violations, so each is instead proven by driving its builder with
    the data present -- that is what the Execution axis claims.

``GAPS``
    No code path emits it. Real compliance gaps, recorded with the
    FEATURES row each one bears on.

``INBOUND``
    Required of a message open-vi receives. An obligation to *parse*,
    not to emit, so the corpus cannot speak to it. Recorded, deferred,
    and listed rather than skipped.

The corpus is the one in tests/golden: captured from real publish
calls, so a field appears here only if the publish path produced it.
"""

from __future__ import annotations

import pathlib
import uuid
from xml.etree import ElementTree as ET

import pytest

import agra_schema
import spec_interactions
from open_vi.codec.capability import build_flight_capability_status
from open_vi.codec.control_status import build_control_status
from open_vi.codec.query import build_query_data_request_status
from open_vi.codec.task import build_task_command_status
from open_vi.codec.vehicle_state import build_navigation_report
from open_vi.domain.control import ControlOffer, ControlReadiness
from open_vi.domain.status import ServiceStatusSnapshot
from open_vi.domain.tspi import TspiSnapshot
from open_vi.identity import SystemIdentity

_GOLDEN = pathlib.Path(__file__).parent / "golden"
_SEPARATOR = "\n<!--+-->\n"
_NS = "{https://www.vdl.afrl.af.mil/programs/oam}"

IDENTITY = SystemIdentity.named("open-vi", "open-vi")
_CAPABILITY_ID = uuid.UUID(int=7)

EXPECTED = {"EMITTED": 64, "CONDITIONAL": 9, "GAPS": 18, "INBOUND": 21}
EXPECTED_TOTAL = 120

# (message type, field): the state that makes the codec emit it. Each
# is proven below -- a registry of excuses nobody exercises is how a
# gap gets reclassified as "conditional" and forgotten.
CONDITIONAL = {
    (
        "MA_FlightCapabilityStatusMT",
        "AvailabilityReason",
    ): "readiness carries a reason (§1.2.1.1 collision-avoidance "
    "constraint); AVAILABLE has none to give",
    ("NavigationReportMT", "Fuel"): "the snapshot has fuel mass",
    ("NavigationReportMT", "Duration"): "the snapshot has endurance",
    (
        "ControlStatusMT",
        "SecondaryController",
    ): "a controller holds the capability, with both IDs stored",
    (
        "MA_TaskCommandStatusMT",
        "CommandProcessingStateReason",
    ): "the task command is rejected",
    (
        "QueryDataRequestStatusMT",
        "RequestProcessingStateReason",
    ): "the query fails",
}

# (message type, field): nothing emits it. The note names what would
# have to change, so the row is actionable rather than just recorded.
GAPS = {
    (
        "MA_ControlRequestStatusMT",
        "ApprovalRequestProcessingStateReason",
    ): "MA_ControlRequestStatusMDT extends RequestStatusBaseType, so it "
    "has two optional reason elements. build_control_request_status "
    "fills the inherited RequestProcessingStateReason; Tables 1-12 "
    "and 1-13 require the derived ApprovalRequestProcessingStateReason. "
    "Both are [0..1], so the XSD and Table 1-38 both pass. "
    "FEATURES §1.2.2.7, §1.2.2.8",
    (
        "MA_FaultMT",
        "Severity",
    ): "build_ma_fault emits FaultID, FaultState, FaultCode and "
    "FaultDescription only. FEATURES §1.2.1.4, §1.2.1.5, §1.2.6.1",
    ("MA_FaultMT", "DetectionTime"): "see Severity. FaultSnapshot has no "
    "detection time. FEATURES §1.2.1.4, §1.2.1.5",
    ("MA_FaultMT", "SubsystemID"): "see Severity. FEATURES §1.2.1.4, §1.2.1.5",
    ("MA_FaultMT", "FaultCodeCount"): "see Severity. FEATURES §1.2.1.4, "
    "§1.2.1.5",
    ("MA_FaultMT", "FaultData"): "see Severity. FEATURES §1.2.1.4, §1.2.1.5",
    ("MA_FaultMT", "AmbiguityGroup"): "see Severity. FEATURES §1.2.1.4, "
    "§1.2.1.5",
    (
        "MA_FaultMT",
        "ServiceID",
    ): "the MA_Fault envelope carries no MessageHeader/ServiceID, though "
    "other messages do. FEATURES §1.2.1.4, §1.2.1.5",
    (
        "MA_SystemNotificationMT",
        "NotificationDetail",
    ): "no builder emits it. FEATURES §1.2.2.5",
}

# Required of messages open-vi receives. Satisfying these means the
# codec extracts the field and the Isolator acts on it, which the
# published corpus cannot show. Deferred, not dismissed.
INBOUND = {
    ("MA_ControlRequestMT", "CapabilityID"),
    ("MA_ControlRequestMT", "ServiceID"),
    ("MA_FlightCommandMT", "CurveFollowing"),
    ("MA_FlightCommandMT", "HSA_CSA"),
    ("MA_FlightCommandMT", "Requirement"),
    ("MA_FlightCommandMT", "Traceability"),
    ("MA_FlightCommandMT", "WaypointFollowing"),
    ("MA_MissionPlanActivationCommandMT", "BySubPlan"),
    ("MA_MissionPlanActivationCommandMT", "CommandType"),
    ("MA_MissionPlanActivationCommandMT", "RoutePlan"),
    ("MA_ResponseMT", "ActivatePlan"),
    ("MA_ResponseMT", "BySubPlan"),
    ("MA_ResponseMT", "RoutePlan"),
    ("MA_ResponseMT", "System"),
    ("MA_ResponseMT", "SystemID"),
    ("QueryDataRequestMT", "Query"),
    ("RoutePlanValidationCommandMT", "WeatherAreaData"),
}


def _corpus(element_name: str) -> set[str] | None:
    """Element names in the published corpus for *element_name*."""
    path = _GOLDEN / f"{element_name}.xml"
    if not path.is_file():
        return None
    names: set[str] = set()
    for document in path.read_text().split(_SEPARATOR):
        document = document.strip()
        if document:
            names.update(
                node.tag.replace(_NS, "")
                for node in ET.fromstring(document).iter()
            )
    return names


def _classify() -> dict[str, list[tuple[str, str, str]]]:
    """Every obligation as ``{bucket: [(table, message type, field)]}``."""
    buckets: dict[str, list[tuple[str, str, str]]] = {
        "EMITTED": [],
        "CONDITIONAL": [],
        "GAPS": [],
        "INBOUND": [],
        "NOT_IN_TYPE": [],
        "UNCLASSIFIED": [],
    }
    for table, message, field in spec_interactions.required_fields():
        entry = (table, message.mms_type, field.name)
        pair = (message.mms_type, field.name)
        if agra_schema.element_path(*pair) is None:
            buckets["NOT_IN_TYPE"].append(entry)
            continue
        published = _corpus(message.element_name)
        if published is None:
            buckets["INBOUND" if pair in INBOUND else "UNCLASSIFIED"].append(
                entry
            )
        elif field.name in published:
            buckets["EMITTED"].append(entry)
        elif pair in CONDITIONAL:
            buckets["CONDITIONAL"].append(entry)
        elif pair in GAPS:
            buckets["GAPS"].append(entry)
        else:
            buckets["UNCLASSIFIED"].append(entry)
    return buckets


@pytest.fixture(scope="module")
def buckets() -> dict[str, list[tuple[str, str, str]]]:
    if not spec_interactions.required_fields():
        pytest.skip(
            "no Vehicle Interface Volume: run ./scripts/fetch-agra-spec.sh"
        )
    if agra_schema.load() is None:
        pytest.skip("no A-GRA schema: run ./scripts/fetch-agra-schema.sh")
    return _classify()


# --- the accounting ----------------------------------------------------


def test_every_obligation_is_accounted_for(buckets) -> None:
    """Nothing silently skipped. A new obligation lands here first."""
    assert not buckets["UNCLASSIFIED"], (
        "obligations in no bucket -- classify each as emitted, "
        f"conditional, a gap, or inbound: {sorted(buckets['UNCLASSIFIED'])}"
    )
    assert sum(len(v) for v in buckets.values()) == EXPECTED_TOTAL


def test_bucket_sizes_are_the_recorded_ones(buckets) -> None:
    """Pins the split so a regression cannot hide as a reclassification."""
    sizes = {name: len(buckets[name]) for name in EXPECTED}
    assert sizes == EXPECTED
    assert len(buckets["NOT_IN_TYPE"]) == len(
        spec_interactions.FIELDS_NOT_IN_TYPE
    )


def test_emitted_fields_really_are_in_the_corpus(buckets) -> None:
    """The 64 checked obligations, re-derived rather than trusted."""
    for table, message_type, field in buckets["EMITTED"]:
        element = spec_interactions.MMS_TYPE_OVERRIDES.get(
            message_type, message_type
        ).removesuffix("MT")
        published = _corpus(element)
        assert published is not None and field in published, (
            f"{table}: {element} no longer emits {field}"
        )


def test_no_registry_entry_is_stale(buckets) -> None:
    """A registry outliving its reason stops the suite noticing the next one."""
    for name, registry in (
        ("CONDITIONAL", set(CONDITIONAL)),
        ("GAPS", set(GAPS)),
        ("INBOUND", INBOUND),
    ):
        live = {(mt, field) for _, mt, field in buckets[name]}
        assert registry == live, (
            f"{name} drifted:\n"
            f"  recorded but not reached: {sorted(registry - live)}\n"
            f"  reached but not recorded: {sorted(live - registry)}"
        )


def test_recorded_gaps_are_still_gaps(buckets) -> None:
    """Fixing a gap must update the registry, not just the code.

    Otherwise a fix and a regression look alike from here.
    """
    for message_type, field in sorted(GAPS):
        element = message_type.removesuffix("MT")
        published = _corpus(element)
        assert published is not None, element
        assert field not in published, (
            f"{element} now emits {field} -- drop it from GAPS and "
            f"update the FEATURES row named in its note"
        )


def test_every_gap_cites_a_features_row() -> None:
    """A gap with no row to correct is unactionable."""
    for pair, note in sorted(GAPS.items()):
        assert "FEATURES §" in note, f"{pair} has no FEATURES citation"


# --- the conditional fields, proven by driving the state ---------------


def _emits(payload: bytes, field: str) -> bool:
    return any(
        node.tag.replace(_NS, "") == field
        for node in ET.fromstring(payload).iter()
    )


def test_availability_reason_is_emitted_when_readiness_has_one() -> None:
    """Table 1-1 (§1.2.1.1): why the flight capability went unavailable."""
    payload = build_flight_capability_status(
        IDENTITY,
        ControlReadiness(
            available=False,
            availability="UNAVAILABLE",
            reason="CONSTRAINT_COLLISION_AVOIDANCE",
        ),
        capability_id=_CAPABILITY_ID,
    )
    assert _emits(payload, "AvailabilityReason")
    nominal = build_flight_capability_status(
        IDENTITY, ControlReadiness(), capability_id=_CAPABILITY_ID
    )
    assert not _emits(nominal, "AvailabilityReason"), (
        "AVAILABLE has no reason to report; emitting one would be noise"
    )


def test_navigation_report_endurance_is_emitted_when_known() -> None:
    """Table 1-15 (§1.2.3.1) requires Fuel, Percent and Duration."""
    payload = build_navigation_report(
        IDENTITY, TspiSnapshot(fuel_mass_kg=410.0, fuel_duration_s=3600.0)
    )
    for field in ("Fuel", "Duration", "Percent"):
        assert _emits(payload, field), field


def test_secondary_controller_is_emitted_once_control_is_held() -> None:
    """Table 1-26 (§1.2.6.2). Both IDs are needed; the schema says so."""
    payload = build_control_status(
        IDENTITY,
        capability_id=_CAPABILITY_ID,
        offer=ControlOffer(),
        service=ServiceStatusSnapshot(service_id=uuid.UUID(int=3)),
        secondary_system_id=uuid.UUID(int=11),
        secondary_service_id=uuid.UUID(int=12),
        in_mission=True,
    )
    assert _emits(payload, "SecondaryController")
    assert _emits(payload, "PrimaryController")


def test_task_command_rejection_carries_its_reason() -> None:
    """Table 1-10 (§1.2.2.5)."""
    payload = build_task_command_status(
        IDENTITY,
        command_id=_CAPABILITY_ID,
        processing_state="REJECTED",
        reason="INVALID_INPUT_PARAMETER",
        reason_description="no Flight task in MA_TaskCommand",
    )
    assert _emits(payload, "CommandProcessingStateReason")


def test_query_failure_carries_its_reason() -> None:
    """Tables 1-16, 1-27, 1-28 and 1-35 all require it on the FAILED leg."""
    payload = build_query_data_request_status(
        IDENTITY,
        request_id=_CAPABILITY_ID,
        processing_state="FAILED",
        reason="INVALID_INPUT_PARAMETER",
        reason_description="unsupported query type",
    )
    assert _emits(payload, "RequestProcessingStateReason")


def test_every_conditional_field_has_a_proof() -> None:
    """Each CONDITIONAL entry is driven by a test in this module.

    Keeps the bucket from becoming a place to put inconvenient gaps:
    the claim "the codec can emit this" has to be executed somewhere.
    """
    source = pathlib.Path(__file__).read_text()
    for message_type, field in sorted(CONDITIONAL):
        assert f'"{field}"' in source, (
            f"{message_type}.{field} is listed CONDITIONAL but no test "
            f"in this module drives it"
        )
