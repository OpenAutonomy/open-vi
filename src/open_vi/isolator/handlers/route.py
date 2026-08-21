"""Inbound route activation + MA_RoutePlan → status / File* outs."""

from __future__ import annotations

import logging
from uuid import uuid4

from open_vi.codec.command import build_flight_activity
from open_vi.codec.mts import (
    MT_ACTIVATION_COMMAND,
    MT_ACTIVATION_STATUS,
    MT_FILE_LOCATION,
    MT_FILE_METADATA,
    MT_FLIGHT_ACTIVITY,
    MT_MISSION_PLAN_ACTIVATION_STATUS,
    MT_ROUTE_PLAN,
    MT_ROUTE_VALIDATION,
    MT_ROUTE_VALIDATION_COMMAND,
    MT_ROUTE_VALIDATION_STATUS,
    MT_SYSTEM_NOTIFICATION,
)
from open_vi.codec.notification import build_system_notification
from open_vi.codec.route import (
    build_file_location_for_route,
    build_file_metadata_for_route,
    build_mission_plan_activation_status,
    build_route_activation_status,
    build_route_plan_validation,
    build_route_plan_validation_command_status,
    parse_route_activation_commands,
    parse_route_plan_id,
    parse_route_plan_waypoints,
    parse_route_validation_command,
)
from open_vi.domain import (
    FlightCommandRequest,
    RouteActivationRequest,
    RouteActivationResult,
    finite_waypoint_geometry,
    is_live_activity,
)
from open_vi.isolator import publishers
from open_vi.isolator.compliance import STATUS_LADDER
from open_vi.isolator.context import IsolatorContext

LOGGER = logging.getLogger(__name__)


class RouteHandler:
    """Loose/Strict route prepare/activate/deactivate + RoutePlan upload."""

    inbound_mts = (
        MT_ACTIVATION_COMMAND,
        MT_ROUTE_PLAN,
        MT_ROUTE_VALIDATION_COMMAND,
    )

    def handles(self, message_type: str) -> bool:
        return message_type in self.inbound_mts

    def handle(self, message_type: str, xml: str, ctx: IsolatorContext) -> None:
        if message_type == MT_ACTIVATION_COMMAND:
            self._handle_activation(xml, ctx)
        elif message_type == MT_ROUTE_PLAN:
            self._handle_route_plan(xml, ctx)
        elif message_type == MT_ROUTE_VALIDATION_COMMAND:
            self._handle_validation(xml, ctx)

    def _handle_activation(self, xml: str, ctx: IsolatorContext) -> None:
        try:
            commands = parse_route_activation_commands(xml)
        except ValueError:
            LOGGER.exception("Failed to parse %s", MT_ACTIVATION_COMMAND)
            return
        if not commands:
            LOGGER.warning(
                "%s contained no RoutePlan commands", MT_ACTIVATION_COMMAND
            )
            return
        for req in commands:
            result = ctx.routes.handle_activation(req)
            if (
                result.awaiting_vehicle
                and result.processing_state == "ACCEPTED"
            ):
                if req.command_type == "ACTIVATE":
                    result = self._activate_vehicle(ctx, req, result)
                elif req.command_type == "DEACTIVATE":
                    result = self._deactivate_vehicle(ctx, req, result)
            self._publish_statuses(ctx, req, result)
            self._publish_plan_activation_status(ctx, req, result)
            LOGGER.info(
                "Route %s %s → %s (%s)",
                req.command_type,
                req.route_plan_id.hex,
                result.processing_state,
                result.plan_state,
            )

    def _activate_vehicle(
        self,
        ctx: IsolatorContext,
        req: RouteActivationRequest,
        pending: RouteActivationResult,
    ) -> RouteActivationResult:
        """Submit WAYPOINT_FOLLOWING; commit ACTIVATED only on accept."""
        stored = ctx.routes.get(req.route_plan_id)
        if stored is None:
            return RouteActivationResult(
                processing_state="REJECTED",
                plan_state=pending.plan_state,
                emit_pair=False,
                reason="INVALID_INPUT_PARAMETER",
                reason_description="No stored MA_RoutePlan for ACTIVATE",
            )
        try:
            waypoints = parse_route_plan_waypoints(stored.xml)
        except ValueError:
            waypoints = ()
        if not finite_waypoint_geometry(waypoints):
            return RouteActivationResult(
                processing_state="REJECTED",
                plan_state=pending.plan_state,
                emit_pair=False,
                reason="INVALID_INPUT_PARAMETER",
                reason_description="MA_RoutePlan has no flyable waypoints",
            )
        live = ctx.platform.active_flight_activity()
        command_id = uuid4()
        if is_live_activity(live):
            activity_id = ctx.flight.activity_id
            if activity_id is None and live is not None:
                activity_id = live.activity_id
            cmd = FlightCommandRequest(
                command_id=command_id,
                capability_id=ctx.state.capability_id,
                command_state="UPDATE",
                mode="WAYPOINT_FOLLOWING",
                waypoints=waypoints,
                choice="Activity",
                activity_id=activity_id,
            )
        else:
            cmd = FlightCommandRequest(
                command_id=command_id,
                capability_id=ctx.state.capability_id,
                command_state="NEW",
                mode="WAYPOINT_FOLLOWING",
                waypoints=waypoints,
                choice="Capability",
            )
        flight = ctx.platform.submit_flight_command(cmd)
        if flight.processing_state != "ACCEPTED":
            return RouteActivationResult(
                processing_state="REJECTED",
                plan_state=pending.plan_state,
                emit_pair=False,
                reason=flight.reason,
                reason_description=flight.reason_description,
            )
        ctx.routes.commit(req.route_plan_id, "ACTIVATED")
        ctx.execution.activate(req.route_plan_id, command_id)
        if flight.activity_id is not None:
            ctx.flight.begin(flight.activity_id)
        activity = ctx.platform.active_flight_activity()
        if activity is not None:
            ctx.bus.publish(
                MT_FLIGHT_ACTIVITY,
                build_flight_activity(
                    ctx.identity,
                    activity,
                    schema_version=ctx.schema_version,
                    mode=ctx.message_mode,
                    object_state="NEW" if flight.new_activity else "UPDATED",
                ),
            )
        publishers.publish_plan_execution(ctx)
        return RouteActivationResult(
            processing_state="ACCEPTED",
            plan_state="ACTIVATED",
            progress_state=pending.progress_state,
            emit_pair=True,
        )

    def _deactivate_vehicle(
        self,
        ctx: IsolatorContext,
        req: RouteActivationRequest,
        pending: RouteActivationResult,
    ) -> RouteActivationResult:
        """CANCEL a route-sourced command, then commit DEACTIVATED."""
        command_id = ctx.execution.command_id
        if command_id is not None:
            cancel = ctx.platform.submit_flight_command(
                FlightCommandRequest(
                    command_id=command_id,
                    capability_id=ctx.state.capability_id,
                    command_state="CANCEL",
                    mode=None,
                    choice="Capability",
                )
            )
            if cancel.processing_state == "REJECTED":
                return RouteActivationResult(
                    processing_state="REJECTED",
                    plan_state=pending.plan_state,
                    emit_pair=False,
                    reason=cancel.reason,
                    reason_description=cancel.reason_description,
                )
            ctx.execution.mark_failed()
            publishers.publish_plan_execution(ctx)
        ctx.routes.commit(req.route_plan_id, "DEACTIVATED")
        ctx.execution.clear()
        ctx.flight.clear()
        return RouteActivationResult(
            processing_state="ACCEPTED",
            plan_state="DEACTIVATED",
            emit_pair=False,
        )

    def _publish_statuses(
        self,
        ctx: IsolatorContext,
        req: RouteActivationRequest,
        result: RouteActivationResult,
    ) -> None:
        schema = ctx.schema_version
        mode = ctx.message_mode
        if result.processing_state == "REJECTED" or not result.emit_pair:
            ctx.bus.publish(
                MT_ACTIVATION_STATUS,
                build_route_activation_status(
                    ctx.identity,
                    command_id=req.command_id,
                    route_plan_id=req.route_plan_id,
                    result=result,
                    schema_version=schema,
                    mode=mode,
                ),
            )
            return
        mid = result.progress_state or result.plan_state
        for command_status in STATUS_LADDER:
            plan_state = (
                result.plan_state if command_status == "COMPLETED" else mid
            )
            ctx.bus.publish(
                MT_ACTIVATION_STATUS,
                build_route_activation_status(
                    ctx.identity,
                    command_id=req.command_id,
                    route_plan_id=req.route_plan_id,
                    result=result,
                    plan_state=plan_state,
                    command_status=command_status,
                    schema_version=schema,
                    mode=mode,
                ),
            )

    def _publish_plan_activation_status(
        self,
        ctx: IsolatorContext,
        req: RouteActivationRequest,
        result: RouteActivationResult,
    ) -> None:
        """Publish ``MissionPlanActivationStatus`` after inbound DEACTIVATE.

        Only on ``ACCEPTED`` → ``DEACTIVATED``. Rejects leave the
        stored plan state unchanged, so this out is omitted.
        """
        if (
            req.command_type != "DEACTIVATE"
            or result.processing_state != "ACCEPTED"
            or result.plan_state != "DEACTIVATED"
        ):
            return
        ctx.bus.publish(
            MT_MISSION_PLAN_ACTIVATION_STATUS,
            build_mission_plan_activation_status(
                ctx.identity,
                mission_plan_id=req.mission_plan_id,
                plan_activation_state="DEACTIVATED",
                route_plan_id=req.route_plan_id,
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            ),
        )

    def _handle_route_plan(self, xml: str, ctx: IsolatorContext) -> None:
        try:
            route_plan_id = parse_route_plan_id(xml)
        except ValueError:
            LOGGER.exception("Failed to parse %s", MT_ROUTE_PLAN)
            return
        body = xml if isinstance(xml, str) else xml.decode("utf-8")
        already = ctx.routes.get(route_plan_id) is not None
        stored = ctx.routes.ingest(route_plan_id, body)
        if already:
            LOGGER.info(
                "Updated stored %s %s (no File* re-emit)",
                MT_ROUTE_PLAN,
                route_plan_id.hex,
            )
            return
        service = ctx.platform.get_service_status()
        schema = ctx.schema_version
        mode = ctx.message_mode
        file_metadata_id = uuid4()
        file_location_id = uuid4()
        ctx.bus.publish(
            MT_SYSTEM_NOTIFICATION,
            build_system_notification(
                ctx.identity,
                associated_message_type="MA_ROUTE_PLAN",
                associated_id=route_plan_id,
                service=service,
                schema_version=schema,
                mode=mode,
            ),
        )
        ctx.bus.publish(
            MT_FILE_LOCATION,
            build_file_location_for_route(
                ctx.identity,
                stored,
                file_location_id=file_location_id,
                file_metadata_id=file_metadata_id,
                schema_version=schema,
                mode=mode,
            ),
        )
        ctx.bus.publish(
            MT_FILE_METADATA,
            build_file_metadata_for_route(
                ctx.identity,
                stored,
                file_metadata_id=file_metadata_id,
                schema_version=schema,
                mode=mode,
            ),
        )
        LOGGER.info(
            "Stored %s %s → Notification + FileLocation + FileMetadata",
            MT_ROUTE_PLAN,
            route_plan_id.hex,
        )

    def _handle_validation(self, xml: str, ctx: IsolatorContext) -> None:
        try:
            cmd = parse_route_validation_command(xml)
        except ValueError:
            LOGGER.exception("Failed to parse %s", MT_ROUTE_VALIDATION_COMMAND)
            return
        if cmd is None:
            LOGGER.warning(
                "%s missing CommandID; dropping", MT_ROUTE_VALIDATION_COMMAND
            )
            return
        schema = ctx.schema_version
        mode = ctx.message_mode
        if cmd.route_plan_id is None:
            ctx.bus.publish(
                MT_ROUTE_VALIDATION_STATUS,
                build_route_plan_validation_command_status(
                    ctx.identity,
                    command_id=cmd.command_id,
                    processing_state="REJECTED",
                    schema_version=schema,
                    mode=mode,
                ),
            )
            return
        stored = ctx.routes.get(cmd.route_plan_id)
        validation_state = "INVALID"
        if stored is not None:
            try:
                waypoints = parse_route_plan_waypoints(stored.xml)
            except ValueError:
                waypoints = ()
            if finite_waypoint_geometry(waypoints):
                validation_state = "VALID"
        validation_id = uuid4()
        ctx.bus.publish(
            MT_ROUTE_VALIDATION,
            build_route_plan_validation(
                ctx.identity,
                validation_id=validation_id,
                route_plan_id=cmd.route_plan_id,
                validation_state=validation_state,
                schema_version=schema,
                mode=mode,
            ),
        )
        processing = "ACCEPTED"
        for command_status in STATUS_LADDER:
            ctx.bus.publish(
                MT_ROUTE_VALIDATION_STATUS,
                build_route_plan_validation_command_status(
                    ctx.identity,
                    command_id=cmd.command_id,
                    processing_state=processing,
                    command_status=command_status,
                    validation_id=validation_id,
                    schema_version=schema,
                    mode=mode,
                ),
            )
        LOGGER.info(
            "%s %s → %s validation=%s",
            MT_ROUTE_VALIDATION_COMMAND,
            cmd.route_plan_id.hex,
            validation_state,
            validation_id.hex,
        )
