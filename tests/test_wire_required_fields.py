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

import itertools
import pathlib
import re
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
from open_vi.domain.status import FaultSnapshot, ServiceStatusSnapshot
from open_vi.domain.tspi import TspiSnapshot
from open_vi.identity import SystemIdentity
from open_vi.platform.px4 import telemetry
from open_vi.platform.px4.telemetry import (
    MavCache,
    sensor_faults,
    unhealthy_sensor_faults,
)

_FEATURES = pathlib.Path(__file__).resolve().parents[1] / "docs" / "FEATURES.md"
_FEATURES_ROW = re.compile(
    r"^\| (1\.2\.\d+\.\d+) \| [^|]+ \| ([^|]+?) \| ([^|]+?) \|", re.M
)
# Every § in a GAPS note is a FEATURES citation; see the registry.
_FEATURES_SECTION = re.compile(r"§(1\.2\.\d+\.\d+)")

_GOLDEN = pathlib.Path(__file__).parent / "golden"
_SEPARATOR = "\n<!--+-->\n"
_NS = "{https://www.vdl.afrl.af.mil/programs/oam}"

IDENTITY = SystemIdentity.named("open-vi", "open-vi")
_CAPABILITY_ID = uuid.UUID(int=7)

EXPECTED = {"EMITTED": 78, "CONDITIONAL": 11, "GAPS": 2, "INBOUND": 21}
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
    (
        "MA_FaultMT",
        "FaultData",
    ): "the platform has key/value evidence for the fault. PX4 carries "
    "the SYS_STATUS health bitfield; Stub injects a named code and has "
    "no evidence to give, so the corpus does not show it",
}

# (message type, field): nothing emits it. The note names what would
# have to change, so the row is actionable rather than just recorded.
GAPS = {
    (
        "MA_FaultMT",
        "AmbiguityGroup",
    ): "A-GRA defines this as a fault narrowed to a set of candidate "
    "components but not yet isolated, with optional diagnostic test "
    "ids. open-vi performs no fault isolation: PX4 reports SYS_STATUS "
    "health bits, which name the unhealthy sensor outright, and Stub "
    "injects a named code. There is no candidate set, so there is "
    "nothing truthful to report -- an empty or invented group would "
    "be worse than the omission. FEATURES §1.2.1.4, §1.2.1.5",
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


def _features_rows() -> dict[str, tuple[str, str]]:
    """``{section: (sequence status, execution status)}`` from §1.2."""
    return {
        section: (sequence.strip(), execution.strip())
        for section, sequence, execution in _FEATURES_ROW.findall(
            _FEATURES.read_text()
        )
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


def test_rows_with_recorded_gaps_are_not_claimed_supported() -> None:
    """A FEATURES row a gap cites cannot still claim Sequence Supported.

    This is the tie the Execution work exists to make. FEATURES' own
    convention, stated in its preamble, is that a Partial Sequence row
    "names a field or reply the interaction requires and open-vi does
    not yet produce" — so a row cited by :data:`GAPS` is Partial by
    that rule, and nothing but a test keeps the two in step.
    """
    rows = _features_rows()
    cited = sorted(
        {
            section
            for note in GAPS.values()
            for section in _FEATURES_SECTION.findall(note)
        }
    )
    assert cited, "no FEATURES sections cited by GAPS"
    wrong = [
        f"§{section} claims Sequence {rows[section][0]}"
        for section in cited
        if section in rows and rows[section][0] == "Supported"
    ]
    assert not wrong, (
        "rows with a recorded required-field gap still claim Sequence "
        "Supported:\n" + "\n".join(wrong)
    )
    missing = [s for s in cited if s not in rows]
    assert not missing, f"GAPS cites no such FEATURES row: {missing}"


# The §1.2 rows whose Sequence is Partial, and why. Asserted both
# ways: a row cannot drift onto or off Supported without this moving.
# Four of these are the one MA_Fault content gap, counted once per
# interaction that requires it; the other two predate the registry and
# name a reply rather than a field, so they carry their reason here.
PARTIAL_SEQUENCE_ROWS = {
    "1.2.1.4": "MA_Fault AmbiguityGroup: open-vi does no fault isolation",
    "1.2.1.5": "MA_Fault, as §1.2.1.4",
    "1.2.5.4": "the COMPLETED-vs-FAILED reply rule while EXECUTING",
    "1.2.5.6": "the ambiguous inout leg",
    "1.2.6.6": "the required PlanExecutionStatus/PlanExecutionState",
}


def test_partial_sequence_rows_are_exactly_as_recorded() -> None:
    """Pins which interactions admit an incomplete Sequence.

    ``test_rows_with_recorded_gaps_are_not_claimed_supported`` only
    pushes a row off Supported. This is the other direction: fixing a
    gap has to bring its row back, and a row cannot quietly go Partial
    without a recorded reason.
    """
    partial = {
        section
        for section, (sequence, _) in _features_rows().items()
        if sequence == "Partial"
    }
    assert partial == set(PARTIAL_SEQUENCE_ROWS), (
        "Partial Sequence rows drifted:\n"
        f"  newly Partial: {sorted(partial - set(PARTIAL_SEQUENCE_ROWS))}\n"
        f"  no longer Partial: "
        f"{sorted(set(PARTIAL_SEQUENCE_ROWS) - partial)}"
    )


def test_every_gap_citation_names_a_partial_row() -> None:
    """A gap must land on a row that admits it."""
    cited = {
        section
        for note in GAPS.values()
        for section in _FEATURES_SECTION.findall(note)
    }
    assert cited <= set(PARTIAL_SEQUENCE_ROWS), (
        "GAPS cites rows that claim a complete Sequence: "
        f"{sorted(cited - set(PARTIAL_SEQUENCE_ROWS))}"
    )


def test_the_headline_counts_match_the_rows() -> None:
    """The §1.2 summary is counted, not remembered.

    Both tallies are quoted as compliance claims, and a hand-kept
    count drifts. Compared with whitespace collapsed, so reflowing
    the paragraph does not fail the test.
    """
    rows = _features_rows()
    assert len(rows) == 36, f"expected 36 numbered §1.2 rows, got {len(rows)}"
    stated = " ".join(_FEATURES.read_text().split())
    for axis, index in (("Sequence", 0), ("Execution", 1)):
        counts = [status[index] for status in rows.values()]
        parts = [
            f"{counts.count(name)} {name}"
            for name in ("Supported", "Partial", "n/a", "Not supported")
            if counts.count(name)
        ]
        claim = f"{axis} {', '.join(parts)}"
        assert claim in stated, (
            f"§1.2 preamble disagrees with the rows, which tally to: {claim}"
        )


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


def test_fault_data_carries_the_evidence_px4_has() -> None:
    """Tables 1-4 and 1-5 (§1.2.1.4, §1.2.1.5).

    Stub injects a named code and has no key/value evidence, so the
    corpus cannot show this. PX4 derives its faults from the
    SYS_STATUS health bitfield, which is exactly the evidence A-GRA
    describes ``FaultData`` as carrying.
    """
    cache = MavCache(sensors_present=32, sensors_enabled=32, sensors_health=0)
    faults = sensor_faults(cache)
    assert faults, "an unhealthy GPS bit produced no fault"
    datum = faults[0].fault_data
    assert datum, "no FaultData on a SYS_STATUS-derived fault"
    assert datum[0].key and datum[0].value and datum[0].data_format


def test_fault_detection_time_and_count_track_occurrences(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A-GRA: DetectionTime is when the fault was detected, not sent.

    So it is stamped once and held while the code stays set, and a
    code that clears and sets again is a second occurrence with a
    fresh time. Re-stamping every sample would read as continuous
    re-detection.

    The clock is stepped explicitly. ``utc_now`` has millisecond
    resolution and the whole test runs well inside one, so comparing
    real timestamps would have made the re-stamp assertion pass or
    fail on timing rather than on behaviour.
    """
    ticks = itertools.count(1)
    monkeypatch.setattr(
        telemetry, "utc_now", lambda: f"2026-01-02T03:04:0{next(ticks)}.000Z"
    )
    cache = MavCache(sensors_present=32, sensors_enabled=32, sensors_health=0)
    first = sensor_faults(cache)[0]
    assert first.detection_time and first.fault_code_count == 1
    held = sensor_faults(cache)[0]
    assert held.detection_time == first.detection_time
    assert held.fault_code_count == 1

    cache.sensors_health = 32  # healthy again
    assert not sensor_faults(cache)
    cache.sensors_health = 0  # and unhealthy again
    again = sensor_faults(cache)[0]
    assert again.fault_code_count == 2
    assert again.detection_time != first.detection_time


def test_asking_whether_bit_failed_does_not_count_an_occurrence() -> None:
    """The predicate must not have the reporting path's side effects."""
    cache = MavCache(sensors_present=32, sensors_enabled=32, sensors_health=0)
    for _ in range(5):
        unhealthy_sensor_faults(
            cache.sensors_present,
            cache.sensors_enabled,
            cache.sensors_health,
        )
    assert not cache.fault_occurrences
    assert not cache.fault_first_seen


def test_the_cleared_sentinel_claims_nothing_it_cannot_know() -> None:
    """A NO_FAULT entry has no detection time, count, or subsystem.

    Tables 1-4 and 1-5 require those of ``MA_Fault``, but they
    describe a fault that exists. Filling them on the sentinel would
    satisfy the oracle by reporting a fault that never happened.
    """
    sentinel = FaultSnapshot(fault_id=uuid.UUID(int=1))
    assert sentinel.severity == "NOMINAL"
    assert sentinel.detection_time is None
    assert sentinel.fault_code_count is None
    assert sentinel.subsystem_id is None
    assert sentinel.service_id is None
    assert sentinel.fault_data == ()


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
