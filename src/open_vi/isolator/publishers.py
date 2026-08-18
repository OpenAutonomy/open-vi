"""Outbound advertise, status, TSPI, and Stub contingency publishes.

These are not handlers. Isolator calls them from ``start``, the tick
loop, and test helpers. Each function reads
:class:`~open_vi.isolator.context.IsolatorContext` (platform snapshot,
identity, session state) and publishes UCI XML on ``ctx.bus``.
"""

from __future__ import annotations

import logging

from open_vi.codec.capability import (
    build_flight_capability,
    build_flight_capability_status,
)
from open_vi.codec.command import (
    build_flight_activity,
    build_flight_command_status,
)
from open_vi.codec.control_status import (
    build_control_status,
    build_response_plan_execution_status,
)
from open_vi.codec.status import build_ma_fault, build_subsystem_status
from open_vi.codec.vehicle_state import (
    build_component_status,
    build_navigation_report,
    build_position_report_detailed,
    build_weather_observation,
)
from open_vi.domain import FlightActivitySnapshot
from open_vi.isolator.context import IsolatorContext
from open_vi.isolator.handlers.flight_command import (
    MT_FLIGHT_ACTIVITY,
    MT_FLIGHT_COMMAND_STATUS,
)
from open_vi.isolator.handlers.heartbeat import MT_MA_FAULT, MT_SUBSYSTEM_STATUS

LOGGER = logging.getLogger(__name__)

MT_FLIGHT_CAPABILITY = "MA_FlightCapability"
MT_FLIGHT_CAPABILITY_STATUS = "MA_FlightCapabilityStatus"
MT_POSITION_REPORT_DETAILED = "MA_PositionReportDetailed"
MT_WEATHER_OBSERVATION = "WeatherObservation"
MT_NAVIGATION_REPORT = "NavigationReport"
MT_COMPONENT_STATUS = "ComponentStatus"
MT_CONTROL_STATUS = "ControlStatus"
MT_RESPONSE_PLAN_EXECUTION_STATUS = "ResponsePlanExecutionStatus"


def publish_command_updates(ctx: IsolatorContext) -> None:
    """Publish status for commands the platform has newly completed.

    Polls ``PlatformPort.poll_command_updates``. Every update becomes
    ``MA_FlightCommandStatus``. A ``COMPLETED`` command also publishes
    ``MA_FlightActivity`` when the platform still has an active activity.
    """
    for command_id, result in ctx.platform.poll_command_updates():
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
        if result.processing_state != "COMPLETED":
            continue
        activity = ctx.platform.active_flight_activity()
        if activity is None:
            continue
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


def advertise_control(ctx: IsolatorContext) -> None:
    """Publish the control offer, then its readiness status.

    Order is ``MA_FlightCapability`` then
    ``MA_FlightCapabilityStatus``. Records ``state.advertised`` and
    ``state.last_availability`` so the tick can skip a no-op republish
    unless availability changed or ``tick_republish_status`` is on.
    """
    snap = ctx.platform.snapshot()
    ctx.bus.publish(
        MT_FLIGHT_CAPABILITY,
        build_flight_capability(
            ctx.identity,
            snap.offer,
            capability_id=ctx.state.capability_id,
            schema_version=ctx.schema_version,
            mode=ctx.message_mode,
        ),
    )
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
    ctx.state.advertised = True
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


def publish_status_package(ctx: IsolatorContext) -> None:
    """Publish the three periodic status outs, in harness order.

    ``ControlStatus``, ``ResponsePlanExecutionStatus``, then
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
            schema_version=schema,
            mode=mode,
        ),
    )
    bus.publish(
        MT_RESPONSE_PLAN_EXECUTION_STATUS,
        build_response_plan_execution_status(
            ctx.identity, schema_version=schema, mode=mode
        ),
    )
    bus.publish(
        MT_SUBSYSTEM_STATUS,
        build_subsystem_status(
            ctx.identity, subsystem, schema_version=schema, mode=mode
        ),
    )
    LOGGER.info(
        "Published status package: ControlStatus, "
        "ResponsePlanExecutionStatus, SubsystemStatus"
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


def publish_contingency(ctx: IsolatorContext, kind: str) -> None:
    """Inject a Stub contingency and publish its Loose Direction1 outs.

    Calls ``inject_contingency`` on the platform. That method is
    Stub/harness-only and is not on
    :class:`~open_vi.platform.port.PlatformPort` — vehicle
    backends drive readiness through ``snapshot()`` instead.

    ``MECHANICAL_DAMAGE`` publishes ``MA_Fault``.
    ``SENSOR_FAILURE`` publishes ``SubsystemStatus`` then ``MA_Fault``.
    ``COLLISION_AVOIDANCE`` publishes capability status then
    capability (the reverse of :func:`advertise_control`).
    ``CLEAR`` calls :func:`advertise_control`. Other *kind* values
    raise ``ValueError``. A platform without ``inject_contingency``
    raises ``TypeError``.
    """
    inject = getattr(ctx.platform, "inject_contingency", None)
    if inject is None:
        raise TypeError(
            "Platform does not support contingency injection "
            "(StubPlatform-only harness API)"
        )
    inject(kind)
    kind_u = kind.upper()
    schema = ctx.schema_version
    mode = ctx.message_mode
    bus = ctx.bus
    if kind_u == "MECHANICAL_DAMAGE":
        bus.publish(
            MT_MA_FAULT,
            build_ma_fault(
                ctx.identity,
                ctx.platform.get_faults(),
                schema_version=schema,
                mode=mode,
            ),
        )
    elif kind_u == "SENSOR_FAILURE":
        bus.publish(
            MT_SUBSYSTEM_STATUS,
            build_subsystem_status(
                ctx.identity,
                ctx.platform.get_subsystem_status(),
                schema_version=schema,
                mode=mode,
            ),
        )
        bus.publish(
            MT_MA_FAULT,
            build_ma_fault(
                ctx.identity,
                ctx.platform.get_faults(),
                schema_version=schema,
                mode=mode,
            ),
        )
    elif kind_u == "COLLISION_AVOIDANCE":
        snap = ctx.platform.snapshot()
        # Harness order: Status then Capability.
        bus.publish(
            MT_FLIGHT_CAPABILITY_STATUS,
            build_flight_capability_status(
                ctx.identity,
                snap.readiness,
                capability_id=ctx.state.capability_id,
                capability_label=snap.offer.capability_label,
                schema_version=schema,
                mode=mode,
            ),
        )
        bus.publish(
            MT_FLIGHT_CAPABILITY,
            build_flight_capability(
                ctx.identity,
                snap.offer,
                capability_id=ctx.state.capability_id,
                schema_version=schema,
                mode=mode,
            ),
        )
        ctx.state.last_availability = snap.readiness.availability
    elif kind_u == "CLEAR":
        advertise_control(ctx)
    else:
        raise ValueError(f"Unknown contingency kind: {kind}")
    LOGGER.info("Published contingency outs for %s", kind_u)
