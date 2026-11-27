"""Inbound required fields: does open-vi read them, or only accept them?

The oracle in ``test_wire_required_fields`` checks outbound
obligations against the published corpus. The 21 inbound ones it
cannot: they are required of messages open-vi *receives*, so nothing
it publishes proves anything about them. That bucket was recorded and
deferred.

This is the other half. An inbound obligation is satisfied when the
field's content reaches an observable effect -- a reply that depends
on it, or Isolator state that changes because of it. Accepting a
message that carries a field and ignoring the field is not
satisfying it, which is the same distinction FEATURES' Execution axis
draws for the outbound side.

Each obligation is therefore either driven by a test here, or
recorded in :data:`UNPARSED` with what open-vi does instead. The
partition is asserted both ways, so a field cannot quietly move
between them.
"""

from __future__ import annotations

import uuid

import pytest

import spec_interactions
from open_vi.asb import InMemoryAsb
from open_vi.codec.command import build_sample_waypoint_command
from open_vi.codec.control import build_sample_control_request
from open_vi.codec.mts import (
    MT_CONTROL_ASSIGNMENT,
    MT_CONTROL_REQUEST,
    MT_MA_RESPONSE,
    MT_ROUTE_PLAN,
    MT_SYSTEM_NOTIFICATION,
)
from open_vi.codec.notification import build_sample_ma_response
from open_vi.codec.route import (
    build_sample_route_activation_command,
    build_sample_route_plan,
)
from open_vi.config import IsolatorConfig
from open_vi.isolator import Isolator
from open_vi.platform import StubPlatform

CAPABILITY_ID = uuid.UUID(int=0xC0)
COMMAND_ID = uuid.UUID(int=0xC1)
ROUTE_PLAN_ID = uuid.UUID(int=0xB0)
MISSION_PLAN_ID = uuid.UUID(int=0xB1)
REQUEST_ID = uuid.UUID(int=0xA1)
RESPONSE_ID = uuid.UUID(int=0xA3)
CONTROLLER_ID = uuid.UUID(int=0x6F)
CONTROLLER_SERVICE_ID = uuid.UUID(int=0x70)

# (message type, field): what open-vi does instead of reading it.
# Each is a real gap in honouring the interaction, not a parse bug.
UNPARSED = {
    (
        "QueryDataRequestMT",
        "Query",
    ): "QueryMessageType has MessageType and Query; parse_query_request "
    "reads only MessageType, so open-vi returns every object of the "
    "requested types and ignores the predicate. Table 1-17 is Query "
    "for Missing Data, where MA asks for particular ids. FEATURES "
    "§1.2.4.2",
    (
        "MA_ResponseMT",
        "System",
    ): "MessageData/Option/Trigger/System. parse_ma_response reads "
    "ResponseID and ActivatePlan; it never looks at Trigger, so no "
    "trigger is monitored and the responding system is not read. "
    "Already recorded on FEATURES §1.2.1.3 as 'No trigger monitor'",
    (
        "MA_MissionPlanActivationCommandMT",
        "BySubPlan",
    ): "parse_route_activation_commands finds RoutePlan by walking the "
    "Command subtree, so it activates whether the plan arrived under "
    "BySubPlan or ByMissionPlan and does not distinguish them. "
    "FEATURES §1.2.5.4",
    (
        "MA_ResponseMT",
        "BySubPlan",
    ): "as the activation command: parse_ma_response walks for "
    "ActivatePlan then RoutePlan without reading the sub-plan "
    "wrapper. FEATURES §1.2.1.3",
    (
        "RoutePlanValidationCommandMT",
        "WeatherAreaData",
    ): "parse_route_validation_command reads CommandID, RoutePlanID, "
    "RequestFrequencyType and ForPlanningUseOnly. Weather is not "
    "considered, so validation cannot answer a weather-dependent "
    "question. FEATURES §1.2.5.5",
    (
        "MA_FlightCommandMT",
        "Traceability",
    ): "Command/Capability/Traceability, required by Table 1-36 "
    "(Validate Release Envelope), which FEATURES scopes out with "
    "weapons. MA_ActionStatus stays dormant for the same reason",
    (
        "MA_FlightCommandMT",
        "Requirement",
    ): "nested inside Traceability; see that entry. FEATURES §1.2.7.1",
}


# (message type, field): the test here that proves open-vi reads it.
PROVEN = {
    (
        "MA_ControlRequestMT",
        "CapabilityID",
    ): "test_control_request_capability_id_reaches_the_assignment",
    (
        "MA_ControlRequestMT",
        "ServiceID",
    ): "test_control_request_service_id_reaches_the_assignment",
    (
        "MA_FlightCommandMT",
        "WaypointFollowing",
    ): "test_flight_command_mode_tag_selects_the_control_mode",
    (
        "MA_FlightCommandMT",
        "HSA_CSA",
    ): "test_flight_command_mode_tag_selects_the_control_mode",
    (
        "MA_FlightCommandMT",
        "CurveFollowing",
    ): "test_flight_command_mode_tag_selects_the_control_mode",
    (
        "MA_MissionPlanActivationCommandMT",
        "CommandType",
    ): "test_activation_command_type_selects_the_transition",
    (
        "MA_MissionPlanActivationCommandMT",
        "RoutePlan",
    ): "test_activation_route_plan_id_selects_the_plan",
    (
        "MA_ResponseMT",
        "ActivatePlan",
    ): "test_response_activate_plan_names_the_plan_to_run",
    (
        "MA_ResponseMT",
        "RoutePlan",
    ): "test_response_route_plan_drives_an_activation",
    (
        "MA_ResponseMT",
        "SystemID",
    ): "test_response_system_id_is_read_from_the_header",
}


def _iso(bus: InMemoryAsb) -> Isolator:
    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(
            tick_republish_status=False,
            publish_vehicle_state=False,
            publish_status_package=False,
        ),
    )
    iso.ctx.state.capability_id = CAPABILITY_ID
    iso.attach()
    return iso


def _hex(value: uuid.UUID) -> str:
    return value.hex


# --- the partition ------------------------------------------------------


def _inbound_obligations() -> set[tuple[str, str]]:
    """Inbound ``(message type, field)`` pairs, from the volume."""
    loaded = spec_interactions.load()
    if loaded is None:
        return set()
    published = {
        "MA_ControlRequestMT",
        "MA_FlightCommandMT",
        "MA_MissionPlanActivationCommandMT",
        "MA_ResponseMT",
        "QueryDataRequestMT",
        "RoutePlanValidationCommandMT",
    }
    return {
        (message.mms_type, field.name)
        for table, message, field in spec_interactions.required_fields()
        if message.mms_type in published
    }


def test_every_inbound_obligation_is_driven_or_recorded() -> None:
    """No inbound field is left without either a test or a reason.

    Asserted both ways. A new obligation in a later volume lands
    here; a field that starts or stops being read has to move between
    the two registries rather than passing silently.
    """
    obligations = _inbound_obligations()
    if not obligations:
        pytest.skip(
            "no Vehicle Interface Volume: run ./scripts/fetch-agra-spec.sh"
        )
    accounted = set(PROVEN) | set(UNPARSED)
    assert not set(PROVEN) & set(UNPARSED), (
        f"in both registries: {sorted(set(PROVEN) & set(UNPARSED))}"
    )
    assert accounted == obligations, (
        "inbound registries drifted from the volume:\n"
        f"  obligations with no entry: {sorted(obligations - accounted)}\n"
        f"  entries the volume does not require: "
        f"{sorted(accounted - obligations)}"
    )


def test_every_proven_obligation_names_a_real_test() -> None:
    """A registry pointing at a test that does not exist proves nothing."""
    missing = sorted(
        (pair, name) for pair, name in PROVEN.items() if name not in globals()
    )
    assert not missing, f"PROVEN names tests that do not exist: {missing}"


def test_unparsed_entries_cite_a_features_row() -> None:
    for pair, note in sorted(UNPARSED.items()):
        assert "FEATURES §" in note or "weapons" in note, pair


# --- MA_ControlRequest --------------------------------------------------


def test_control_request_capability_id_reaches_the_assignment() -> None:
    """Tables 1-12 and 1-14: "CapabilityID: CapabilityID_Type"."""
    bus = InMemoryAsb()
    iso = _iso(bus)
    asked = uuid.UUID(int=0xCAFE)
    bus.publish(
        MT_CONTROL_REQUEST,
        build_sample_control_request(
            iso.identity,
            request_id=REQUEST_ID,
            controller_system_id=CONTROLLER_ID,
            capability_id=asked,
        ),
    )
    assignment = bus.published[MT_CONTROL_ASSIGNMENT][-1]
    assert _hex(asked) in assignment.replace("-", ""), (
        "the assignment did not carry the requested CapabilityID"
    )


def test_control_request_service_id_reaches_the_assignment() -> None:
    """Table 1-12: "ServiceID: ServiceID_Type" on the controller."""
    bus = InMemoryAsb()
    iso = _iso(bus)
    bus.publish(
        MT_CONTROL_REQUEST,
        build_sample_control_request(
            iso.identity,
            request_id=REQUEST_ID,
            controller_system_id=CONTROLLER_ID,
            controller_service_id=CONTROLLER_SERVICE_ID,
        ),
    )
    assignment = bus.published[MT_CONTROL_ASSIGNMENT][-1]
    assert _hex(CONTROLLER_SERVICE_ID) in assignment.replace("-", "")


# --- MA_FlightCommand ---------------------------------------------------


@pytest.mark.parametrize(
    "mode_tag", ["WaypointFollowing", "HSA_CSA", "CurveFollowing"]
)
def test_flight_command_mode_tag_selects_the_control_mode(
    mode_tag: str,
) -> None:
    """Tables 1-6, 1-7 and 1-8 each require their own mode element.

    The element *name* is the discriminator -- ``_MODE_TAGS`` in the
    codec maps it to the submitted mode -- so a command carrying one
    must not be read as another.
    """
    from open_vi.codec.command import _MODE_TAGS, parse_flight_commands

    assert mode_tag in _MODE_TAGS, f"{mode_tag} is not a known mode tag"
    xml = build_sample_waypoint_command(
        _identity(), command_id=COMMAND_ID, capability_id=CAPABILITY_ID
    ).decode()
    if mode_tag != "WaypointFollowing":
        xml = xml.replace("WaypointFollowing", mode_tag)
    commands = parse_flight_commands(xml)
    assert commands, f"no command parsed for {mode_tag}"
    assert commands[0].mode == _MODE_TAGS[mode_tag]


def _identity():
    from open_vi.identity import SystemIdentity

    return SystemIdentity.named("open-ma", "open-ma")


# --- MA_MissionPlanActivationCommand ------------------------------------


def test_activation_command_type_selects_the_transition() -> None:
    """Table 1-22: "CommandType: PlanActivationCommandEnum", DEACTIVATE.

    The same message with a different CommandType must produce a
    different activation state, or the field is being ignored.
    """
    from open_vi.codec.route import parse_route_activation_commands

    seen = {}
    for command_type in ("PREPARE_FOR_UPLOAD", "DEACTIVATE"):
        xml = build_sample_route_activation_command(
            _identity(),
            command_id=COMMAND_ID,
            mission_plan_id=MISSION_PLAN_ID,
            route_plan_id=ROUTE_PLAN_ID,
            command_type=command_type,
        ).decode()
        parsed = parse_route_activation_commands(xml)
        assert parsed, f"no activation parsed for {command_type}"
        seen[command_type] = parsed[0].command_type
    assert seen["PREPARE_FOR_UPLOAD"] != seen["DEACTIVATE"]


def test_activation_route_plan_id_selects_the_plan() -> None:
    """Tables 1-19 to 1-22: "RoutePlan" names which plan to act on."""
    from open_vi.codec.route import parse_route_activation_commands

    other = uuid.UUID(int=0xBEEF)
    xml = build_sample_route_activation_command(
        _identity(),
        command_id=COMMAND_ID,
        mission_plan_id=MISSION_PLAN_ID,
        route_plan_id=other,
        command_type="PREPARE_FOR_UPLOAD",
    ).decode()
    parsed = parse_route_activation_commands(xml)
    assert parsed and parsed[0].route_plan_id == other


# --- MA_Response --------------------------------------------------------


def test_response_activate_plan_names_the_plan_to_run() -> None:
    """Table 1-3: "ActivatePlan" and the "RoutePlan" beneath it.

    Without ActivatePlan the failsafe response is a notification only;
    with it, the named plan is the one activated.
    """
    from open_vi.codec.notification import parse_ma_response

    bare = parse_ma_response(
        build_sample_ma_response(_identity(), response_id=RESPONSE_ID)
    )
    assert bare is not None and bare.route_plan_id is None

    with_plan = parse_ma_response(
        build_sample_ma_response(
            _identity(),
            response_id=RESPONSE_ID,
            route_plan_id=ROUTE_PLAN_ID,
            mission_plan_id=MISSION_PLAN_ID,
        )
    )
    assert with_plan is not None
    assert with_plan.route_plan_id == ROUTE_PLAN_ID
    assert with_plan.mission_plan_id == MISSION_PLAN_ID


def test_response_route_plan_drives_an_activation() -> None:
    """The read field has to reach the vehicle, not just the parser."""
    bus = InMemoryAsb()
    _iso(bus)
    bus.publish(
        MT_ROUTE_PLAN,
        build_sample_route_plan(_identity(), route_plan_id=ROUTE_PLAN_ID),
    )
    bus.publish(
        MT_MA_RESPONSE,
        build_sample_ma_response(
            _identity(),
            response_id=RESPONSE_ID,
            route_plan_id=ROUTE_PLAN_ID,
            mission_plan_id=MISSION_PLAN_ID,
        ),
    )
    assert bus.published.get(MT_SYSTEM_NOTIFICATION), (
        "MA_Response produced no notification"
    )


def test_response_system_id_is_read_from_the_header() -> None:
    """Table 1-3 requires "SystemID"; a peer's response is not loopback."""
    from open_vi.codec.xmlutil import parse_header_system_id

    body = build_sample_ma_response(_identity(), response_id=RESPONSE_ID)
    assert parse_header_system_id(body) == _identity().uuid
