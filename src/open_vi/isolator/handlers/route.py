"""Inbound route activation + MA_RoutePlan → status / File* outs."""

from __future__ import annotations

import logging
from uuid import uuid4

from open_vi.codec.notification import build_system_notification
from open_vi.codec.route import (
    build_file_location_for_route,
    build_file_metadata_for_route,
    build_route_activation_status,
    build_route_plan_validation,
    build_route_plan_validation_command_status,
    parse_route_activation_commands,
    parse_route_plan_id,
    parse_route_validation_command,
)
from open_vi.domain import RouteActivationRequest, RouteActivationResult
from open_vi.isolator.compliance import STATUS_LADDER
from open_vi.isolator.context import IsolatorContext

LOGGER = logging.getLogger(__name__)

MT_ACTIVATION_COMMAND = "MA_MissionPlanActivationCommand"
MT_ACTIVATION_STATUS = "MA_MissionPlanActivationCommandStatus"
MT_ROUTE_PLAN = "MA_RoutePlan"
MT_SYSTEM_NOTIFICATION = "MA_SystemNotification"
MT_FILE_LOCATION = "FileLocation"
MT_FILE_METADATA = "FileMetadata"
MT_ROUTE_VALIDATION_COMMAND = "RoutePlanValidationCommand"
MT_ROUTE_VALIDATION = "RoutePlanValidation"
MT_ROUTE_VALIDATION_STATUS = "RoutePlanValidationCommandStatus"


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
            self._publish_statuses(ctx, req, result)
            LOGGER.info(
                "Route %s %s → %s (%s)",
                req.command_type,
                req.route_plan_id.hex,
                result.processing_state,
                result.plan_state,
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

    def _handle_route_plan(self, xml: str, ctx: IsolatorContext) -> None:
        try:
            route_plan_id = parse_route_plan_id(xml)
        except ValueError:
            LOGGER.exception("Failed to parse %s", MT_ROUTE_PLAN)
            return
        body = xml if isinstance(xml, str) else xml.decode("utf-8")
        already = ctx.routes.get(route_plan_id) is not None
        stored = ctx.routes.ingest(route_plan_id, body)
        if route_plan_id not in ctx.state.stored_route_ids:
            ctx.state.stored_route_ids.append(route_plan_id)
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
        validation_state = "VALID" if stored is not None else "INVALID"
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
