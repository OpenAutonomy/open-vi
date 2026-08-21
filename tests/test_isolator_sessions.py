"""FlightSession, RouteExecution, and RouteStore.ingested_ids."""

from __future__ import annotations

from uuid import uuid4

from open_vi.isolator.execution import RouteExecution
from open_vi.isolator.flight import FlightSession
from open_vi.isolator.routes import RouteStore


def test_flight_session_begin_and_clear() -> None:
    session = FlightSession()
    assert session.activity_id is None
    activity_id = uuid4()
    session.begin(activity_id)
    assert session.activity_id == activity_id
    session.clear()
    assert session.activity_id is None


def test_route_execution_activate_complete_keeps_ids() -> None:
    execution = RouteExecution()
    plan_id = uuid4()
    command_id = uuid4()
    execution.activate(plan_id, command_id)
    assert execution.plan_id == plan_id
    assert execution.command_id == command_id
    assert execution.state == "EXECUTING"
    assert execution.is_sourced(command_id)
    assert not execution.is_sourced(uuid4())
    execution.complete()
    assert execution.state == "COMPLETED"
    assert execution.plan_id == plan_id
    assert execution.is_sourced(command_id)


def test_route_execution_mark_failed_then_clear() -> None:
    execution = RouteExecution()
    plan_id = uuid4()
    command_id = uuid4()
    execution.activate(plan_id, command_id)
    execution.mark_failed()
    assert execution.state == "FAILED"
    assert execution.plan_id == plan_id
    execution.clear()
    assert execution.plan_id is None
    assert execution.command_id is None
    assert execution.state is None
    assert not execution.is_sourced(command_id)


def test_ingested_ids_skips_prepare_only() -> None:
    store = RouteStore()
    prepared = uuid4()
    ingested = uuid4()
    store.prime(prepared, state="READY_FOR_UPLOAD")
    store.ingest(ingested, "<MA_RoutePlan/>")
    assert store.ingested_ids() == (ingested,)
    assert store.get(prepared) is None
    assert store.get(ingested) is not None
