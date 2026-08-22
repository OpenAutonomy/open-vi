"""Outbound advertise, status, and TSPI publishes.

These are not handlers. Isolator calls them from ``start``, the tick
loop, and test helpers. Each function reads
:class:`~open_vi.isolator.context.IsolatorContext` (platform snapshot,
identity, session state) and publishes UCI XML on ``ctx.bus``.
"""

from __future__ import annotations

import logging
from uuid import UUID

from open_vi.codec.capability import (
    build_flight_capability,
    build_flight_capability_status,
)
from open_vi.codec.command import (
    build_flight_activity,
    build_flight_command_status,
)
from open_vi.codec.control_status import (
    build_activity_plan_execution_status,
    build_control_status,
    build_mission_plan_execution_status,
    build_response_plan_execution_status,
    build_route_activity_plan_execution_status,
    build_route_plan_execution_status,
    build_task_plan_execution_status,
)
from open_vi.codec.mts import (
    MT_ACTIVITY_PLAN_EXECUTION_STATUS,
    MT_COMPONENT_STATUS,
    MT_CONTROL_STATUS,
    MT_FLIGHT_ACTIVITY,
    MT_FLIGHT_CAPABILITY,
    MT_FLIGHT_CAPABILITY_STATUS,
    MT_FLIGHT_COMMAND_STATUS,
    MT_MA_FAULT,
    MT_MISSION_PLAN_ACTIVATION_STATUS,
    MT_MISSION_PLAN_EXECUTION_STATUS,
    MT_NAVIGATION_REPORT,
    MT_POSITION_REPORT_DETAILED,
    MT_RESPONSE_PLAN_EXECUTION_STATUS,
    MT_ROUTE_ACTIVITY_PLAN_EXECUTION_STATUS,
    MT_ROUTE_PLAN_EXECUTION_STATUS,
    MT_SUBSYSTEM_STATUS,
    MT_TASK_PLAN_EXECUTION_STATUS,
    MT_WEATHER_OBSERVATION,
)
from open_vi.codec.route import build_mission_plan_activation_status
from open_vi.codec.status import build_ma_fault, build_subsystem_status
from open_vi.codec.vehicle_state import (
    build_component_status,
    build_navigation_report,
    build_position_report_detailed,
    build_weather_observation,
)
from open_vi.domain import (
    CommandResult,
    FlightActivitySnapshot,
    PlanExecutionSnapshot,
)
from open_vi.isolator.context import IsolatorContext

LOGGER = logging.getLogger(__name__)


def publish_command_updates(
    ctx: IsolatorContext,
    updates: list[tuple[UUID, CommandResult]],
) -> None:
    """Publish status for already-applied command completions.

    Isolator applies session transitions, then calls this. Direct
    flight commands become ``MA_FlightCommandStatus``. A
    route-sourced command id is skipped so ACTIVATE does not leak a
    command MA never sent. A ``COMPLETED`` command still publishes
    ``MA_FlightActivity`` when the platform has an activity. A
    route-sourced ``COMPLETED`` republishes the plan-execution
    family.
    """
    for command_id, result in updates:
        route_sourced = ctx.execution.is_sourced(command_id)
        if not route_sourced:
            ctx.bus.publish(
                MT_FLIGHT_COMMAND_STATUS,
                build_flight_command_status(
                    ctx.identity,
                    command_id=command_id,
                    result=result,
                    schema_version=ctx.schema_version,
                    mode=ctx.message_mode,
                ),
            )
            LOGGER.info(
                "FlightCommand %s → %s",
                command_id.hex,
                result.processing_state,
            )
        else:
            LOGGER.info(
                "Route-sourced command %s → %s",
                command_id.hex,
                result.processing_state,
            )
        if result.processing_state != "COMPLETED":
            continue
        activity = ctx.platform.active_flight_activity()
        if activity is not None:
            ctx.bus.publish(
                MT_FLIGHT_ACTIVITY,
                build_flight_activity(
                    ctx.identity,
                    activity,
                    schema_version=ctx.schema_version,
                    mode=ctx.message_mode,
                    object_state="UPDATED",
                ),
            )
        if route_sourced:
            publish_plan_execution(ctx)


def plan_execution_for_publish(
    ctx: IsolatorContext,
) -> PlanExecutionSnapshot | None:
    """Live route execution, or ``None`` when no route is executing.

    Requires both ``execution.plan_id`` and ``execution.state``.
    ``mission_plan_id`` comes from :class:`~open_vi.isolator.routes.RouteStore`.
    """
    route_id = ctx.execution.plan_id
    execution_state = ctx.execution.state
    if route_id is None or execution_state is None:
        return None
    stored = ctx.routes.get(route_id)
    mission_id = stored.mission_plan_id if stored is not None else None
    return PlanExecutionSnapshot(
        execution_state=execution_state,
        route_plan_id=route_id,
        mission_plan_id=mission_id,
        activity_id=ctx.flight.activity_id,
    )


def publish_mission_plan_activation_status(
    ctx: IsolatorContext,
    *,
    mission_plan_id: UUID,
    plan_activation_state: str,
    route_plan_id: UUID | None = None,
) -> None:
    """Publish ``MissionPlanActivationStatus``. Emit only."""
    ctx.bus.publish(
        MT_MISSION_PLAN_ACTIVATION_STATUS,
        build_mission_plan_activation_status(
            ctx.identity,
            mission_plan_id=mission_plan_id,
            plan_activation_state=plan_activation_state,
            route_plan_id=route_plan_id,
            schema_version=ctx.schema_version,
            mode=ctx.message_mode,
        ),
    )


def publish_plan_execution(ctx: IsolatorContext) -> None:
    """Publish ResponsePlan, idle Activity*/Task, then live Route/Mission."""
    snapshot = plan_execution_for_publish(ctx)
    schema = ctx.schema_version
    mode = ctx.message_mode
    ctx.bus.publish(
        MT_RESPONSE_PLAN_EXECUTION_STATUS,
        build_response_plan_execution_status(
            ctx.identity,
            snapshot=snapshot,
            schema_version=schema,
            mode=mode,
        ),
    )
    ctx.bus.publish(
        MT_ACTIVITY_PLAN_EXECUTION_STATUS,
        build_activity_plan_execution_status(
            ctx.identity, schema_version=schema, mode=mode
        ),
    )
    ctx.bus.publish(
        MT_ROUTE_ACTIVITY_PLAN_EXECUTION_STATUS,
        build_route_activity_plan_execution_status(
            ctx.identity, schema_version=schema, mode=mode
        ),
    )
    ctx.bus.publish(
        MT_TASK_PLAN_EXECUTION_STATUS,
        build_task_plan_execution_status(
            ctx.identity, schema_version=schema, mode=mode
        ),
    )
    if snapshot is None:
        return
    ctx.bus.publish(
        MT_ROUTE_PLAN_EXECUTION_STATUS,
        build_route_plan_execution_status(
            ctx.identity, snapshot, schema_version=schema, mode=mode
        ),
    )
    if snapshot.mission_plan_id is None:
        return
    ctx.bus.publish(
        MT_MISSION_PLAN_EXECUTION_STATUS,
        build_mission_plan_execution_status(
            ctx.identity, snapshot, schema_version=schema, mode=mode
        ),
    )
    LOGGER.info(
        "Published plan execution %s route=%s",
        snapshot.execution_state,
        snapshot.route_plan_id.hex,
    )


def flight_activity_for_publish(ctx: IsolatorContext) -> FlightActivitySnapshot:
    """Platform activity, or an idle ``ENABLED`` placeholder.

    The vehicle-state package always includes ``MA_FlightActivity``.
    When nothing is flying, this uses ``state.idle_activity_id`` so
    the outbound still has a stable activity id.
    """
    activity = ctx.platform.active_flight_activity()
    if activity is not None:
        return activity
    return FlightActivitySnapshot(
        activity_id=ctx.state.idle_activity_id,
        capability_id=ctx.state.capability_id,
        activity_state="ENABLED",
        interactive=False,
    )


def publish_flight_capability(ctx: IsolatorContext) -> None:
    """Publish ``MA_FlightCapability`` from the advertised (redacted) offer."""
    offer = ctx.advertised_offer()
    ctx.bus.publish(
        MT_FLIGHT_CAPABILITY,
        build_flight_capability(
            ctx.identity,
            offer,
            capability_id=ctx.state.capability_id,
            schema_version=ctx.schema_version,
            mode=ctx.message_mode,
        ),
    )


def advertise_control(ctx: IsolatorContext) -> None:
    """Publish the control offer, then its readiness status.

    Order is ``MA_FlightCapability`` then
    ``MA_FlightCapabilityStatus``. Records
    ``state.last_availability`` so the tick can skip a no-op republish
    unless availability changed or ``tick_republish_status`` is on.
    """
    publish_flight_capability(ctx)
    publish_capability_status(ctx)
    snap = ctx.platform.snapshot()
    ctx.state.last_availability = snap.readiness.availability
    LOGGER.info(
        "Advertised %s then %s (%s)",
        MT_FLIGHT_CAPABILITY,
        MT_FLIGHT_CAPABILITY_STATUS,
        snap.readiness.availability,
    )


def publish_capability_status(ctx: IsolatorContext) -> None:
    """Republish ``MA_FlightCapabilityStatus`` only.

    Does not send the offer again and does not update
    ``state.last_availability``. Use :func:`advertise_control` when
    the full pair must stay in sync.
    """
    snap = ctx.platform.snapshot()
    ctx.bus.publish(
        MT_FLIGHT_CAPABILITY_STATUS,
        build_flight_capability_status(
            ctx.identity,
            snap.readiness,
            capability_id=ctx.state.capability_id,
            capability_label=snap.offer.capability_label,
            schema_version=ctx.schema_version,
            mode=ctx.message_mode,
        ),
    )


def publish_faults(ctx: IsolatorContext) -> None:
    """Publish ``MA_Fault`` from ``platform.get_faults()``."""
    ctx.bus.publish(
        MT_MA_FAULT,
        build_ma_fault(
            ctx.identity,
            ctx.platform.get_faults(),
            schema_version=ctx.schema_version,
            mode=ctx.message_mode,
        ),
    )


def publish_subsystem_status(ctx: IsolatorContext) -> None:
    """Publish ``SubsystemStatus`` from the platform."""
    ctx.bus.publish(
        MT_SUBSYSTEM_STATUS,
        build_subsystem_status(
            ctx.identity,
            ctx.platform.get_subsystem_status(),
            schema_version=ctx.schema_version,
            mode=ctx.message_mode,
        ),
    )


def _in_mission(ctx: IsolatorContext) -> bool:
    """True when a flight, route, or task is live."""
    return (
        ctx.flight.activity_id is not None
        or ctx.execution.state == "EXECUTING"
        or ctx.state.active_task_id is not None
    )


def publish_status_package(ctx: IsolatorContext) -> None:
    """Publish the three periodic status outs, in harness order.

    ``ControlStatus``, the plan-execution family, then
    ``SubsystemStatus``. Gated by ``publish_status_package`` on
    Isolator start and tick.
    """
    snap = ctx.platform.snapshot()
    service = ctx.platform.get_service_status()
    subsystem = ctx.platform.get_subsystem_status()
    schema = ctx.schema_version
    mode = ctx.message_mode
    bus = ctx.bus
    bus.publish(
        MT_CONTROL_STATUS,
        build_control_status(
            ctx.identity,
            capability_id=ctx.state.capability_id,
            offer=snap.offer,
            service=service,
            secondary_system_id=ctx.state.controller_system_id,
            secondary_service_id=ctx.state.controller_service_id,
            in_mission=_in_mission(ctx),
            schema_version=schema,
            mode=mode,
        ),
    )
    publish_plan_execution(ctx)
    bus.publish(
        MT_SUBSYSTEM_STATUS,
        build_subsystem_status(
            ctx.identity, subsystem, schema_version=schema, mode=mode
        ),
    )
    LOGGER.info(
        "Published status package: ControlStatus, "
        "plan execution, SubsystemStatus"
    )


def publish_vehicle_state(ctx: IsolatorContext) -> None:
    """Publish the five Receive Vehicle State Data outs, in harness order.

    ``MA_FlightActivity``, ``MA_PositionReportDetailed``,
    ``WeatherObservation``, ``NavigationReport``, then
    ``ComponentStatus``. Activity comes from
    :func:`flight_activity_for_publish`; the rest from
    ``platform.get_vehicle_state()``.
    """
    activity = flight_activity_for_publish(ctx)
    state = ctx.platform.get_vehicle_state()
    identity = ctx.identity
    schema = ctx.schema_version
    mode = ctx.message_mode
    bus = ctx.bus
    bus.publish(
        MT_FLIGHT_ACTIVITY,
        build_flight_activity(
            identity,
            activity,
            schema_version=schema,
            mode=mode,
            object_state="UPDATED",
        ),
    )
    bus.publish(
        MT_POSITION_REPORT_DETAILED,
        build_position_report_detailed(
            identity, state, schema_version=schema, mode=mode
        ),
    )
    bus.publish(
        MT_WEATHER_OBSERVATION,
        build_weather_observation(
            identity, state, schema_version=schema, mode=mode
        ),
    )
    bus.publish(
        MT_NAVIGATION_REPORT,
        build_navigation_report(
            identity, state, schema_version=schema, mode=mode
        ),
    )
    bus.publish(
        MT_COMPONENT_STATUS,
        build_component_status(
            identity, state, schema_version=schema, mode=mode
        ),
    )
    LOGGER.info(
        "Published vehicle state: Activity, PositionReportDetailed, "
        "Weather, Navigation, ComponentStatus"
    )
