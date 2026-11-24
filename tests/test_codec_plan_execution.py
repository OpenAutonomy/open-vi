"""Plan-execution status: the composite shape and the state vocabulary.

A-GRA carries plan execution as a repeating ``PlanExecutionStatus``
composite of a plan id and a state, not as flat sibling fields, and
its ``PlanExecutionStateEnum`` says ``COMPLETE`` where this codebase's
domain says ``COMPLETED``.

The wire corpus in ``test_wire_xsd.py`` did not catch that mismatch:
its capture never drives a route to completion, so it only ever
exercised EXECUTING and FAILED. These tests cover the state
vocabulary directly rather than hoping the corpus reaches it.
"""

from __future__ import annotations

from uuid import UUID
from xml.etree import ElementTree as ET

import pytest

from open_vi.codec.control_status import (
    _PLAN_EXECUTION_STATE,
    build_mission_plan_execution_status,
    build_response_plan_execution_status,
    build_route_plan_execution_status,
    plan_execution_state,
)
from open_vi.codec.ns import NS
from open_vi.domain import PlanExecutionSnapshot
from open_vi.identity import SystemIdentity
from open_vi.isolator.execution import RouteExecution

IDENTITY = SystemIdentity.named("open-vi", "open-vi")
ROUTE = UUID(int=0xB0)
MISSION = UUID(int=0xB1)
ACTIVITY = UUID(int=0xE0)

# PlanExecutionStateEnum, A-GRA 5.0a. Duplicated deliberately: the
# schema-gated check in test_wire_xsd.py reads the real enumeration,
# and this list keeps the vocabulary assertion working for anyone who
# has not fetched the standard.
SCHEMA_STATES = frozenset(
    {"PENDING", "EXECUTING", "COMPLETE", "SUPERCEDED", "CANCELED", "FAILED"}
)


def _snapshot(state: str) -> PlanExecutionSnapshot:
    return PlanExecutionSnapshot(
        execution_state=state,
        route_plan_id=ROUTE,
        mission_plan_id=MISSION,
        activity_id=ACTIVITY,
    )


def _message_data(xml: bytes) -> ET.Element:
    data = ET.fromstring(xml).find(f"{{{NS}}}MessageData")
    assert data is not None
    return data


def _local(node: ET.Element) -> list[str]:
    return [child.tag.rsplit("}", 1)[-1] for child in node]


# --- state vocabulary -------------------------------------------------


def test_completed_maps_to_the_schema_token() -> None:
    """The domain says COMPLETED; A-GRA's token is COMPLETE."""
    assert plan_execution_state("COMPLETED") == "COMPLETE"


def test_every_mapped_token_is_a_schema_state() -> None:
    unknown = sorted(set(_PLAN_EXECUTION_STATE.values()) - SCHEMA_STATES)
    assert not unknown, f"not PlanExecutionStateEnum members: {unknown}"


def test_every_state_route_execution_can_set_has_a_wire_token() -> None:
    """Exercises the real setters, so a new one cannot slip through.

    A domain state with no mapping passes through unchanged and
    becomes invalid XML on the bus. Listing states by hand would miss
    a newly added one; driving the setters does not.
    """
    execution = RouteExecution()
    states = set()
    execution.activate(ROUTE, UUID(int=0xC1))
    states.add(execution.state)
    execution.complete()
    states.add(execution.state)
    execution.mark_failed()
    states.add(execution.state)

    unmapped = sorted(s for s in states if s not in _PLAN_EXECUTION_STATE)
    assert not unmapped, (
        f"RouteExecution can set {unmapped}, which has no wire token"
    )


def test_unmapped_state_passes_through_rather_than_being_rewritten() -> None:
    """Fail loudly downstream, never silently as a valid-looking value."""
    assert plan_execution_state("NOT_A_STATE") == "NOT_A_STATE"


# --- composite shape --------------------------------------------------


@pytest.mark.parametrize("state", sorted(_PLAN_EXECUTION_STATE))
def test_route_status_carries_one_composite(state: str) -> None:
    data = _message_data(
        build_route_plan_execution_status(IDENTITY, _snapshot(state))
    )
    assert _local(data)[:3] == ["SystemID", "Source", "PlanExecutionStatus"]
    composite = data.find(f"{{{NS}}}PlanExecutionStatus")
    assert composite is not None
    assert _local(composite) == ["PlanID", "PlanExecutionState"]
    assert composite.findtext(
        f"{{{NS}}}PlanExecutionState"
    ) == plan_execution_state(state)


def test_mission_status_uses_mission_plan_id() -> None:
    """The mission composite keys on MissionPlanID, not PlanID."""
    data = _message_data(
        build_mission_plan_execution_status(IDENTITY, _snapshot("EXECUTING"))
    )
    composite = data.find(f"{{{NS}}}PlanExecutionStatus")
    assert composite is not None
    assert _local(composite) == ["MissionPlanID", "PlanExecutionState"]


def test_system_id_is_not_executing_system_id() -> None:
    """A-GRA names it SystemID: the system whose plan is statused."""
    for xml in (
        build_route_plan_execution_status(IDENTITY, _snapshot("EXECUTING")),
        build_mission_plan_execution_status(IDENTITY, _snapshot("EXECUTING")),
    ):
        assert b"ExecutingSystemID" not in xml
        assert _local(_message_data(xml))[0] == "SystemID"


def test_activity_id_is_dropped() -> None:
    """No place for it in these content models, so it is not emitted.

    Pinned because the snapshot still carries one: silently emitting
    it again would be invalid, and dropping it is a deliberate loss
    worth keeping visible.
    """
    snapshot = _snapshot("EXECUTING")
    assert snapshot.activity_id is not None
    for xml in (
        build_route_plan_execution_status(IDENTITY, snapshot),
        build_mission_plan_execution_status(IDENTITY, snapshot),
        build_response_plan_execution_status(IDENTITY, snapshot=snapshot),
    ):
        assert b"ActivityID" not in xml


def test_response_status_idle_form_is_system_id_and_source() -> None:
    """The idle form matches its three conformant sibling messages."""
    data = _message_data(build_response_plan_execution_status(IDENTITY))
    assert _local(data) == ["SystemID", "Source"]


def test_response_status_live_form_adds_the_composite() -> None:
    data = _message_data(
        build_response_plan_execution_status(
            IDENTITY, snapshot=_snapshot("EXECUTING")
        )
    )
    assert _local(data) == ["SystemID", "Source", "PlanExecutionStatus"]
