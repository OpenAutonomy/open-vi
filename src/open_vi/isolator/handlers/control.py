"""Inbound MA_ControlRequest → Status + MA_ControlAssignment."""

from __future__ import annotations

import logging

from open_vi.codec.control import (
    ControlRequest,
    build_control_assignment,
    build_control_request_status,
    parse_control_request,
)
from open_vi.codec.mts import (
    MT_CONTROL_ASSIGNMENT,
    MT_CONTROL_REQUEST,
    MT_CONTROL_REQUEST_STATUS,
)
from open_vi.isolator.context import IsolatorContext
from open_vi.isolator.handlers.base import STATUS_LADDER

LOGGER = logging.getLogger(__name__)

_APPROVAL_FOR_LADDER = {
    "QUEUED": "PENDING",
    "PROCESSING": "PENDING",
    "COMPLETED": "APPROVED",
    "REJECTED": "REJECTED",
}


class ControlHandler:
    """Acquire / steal / release control; publish assignment."""

    inbound_mts = (MT_CONTROL_REQUEST,)

    def handles(self, message_type: str) -> bool:
        return message_type == MT_CONTROL_REQUEST

    def handle(self, message_type: str, xml: str, ctx: IsolatorContext) -> None:
        del message_type
        try:
            req = parse_control_request(xml)
        except ValueError:
            LOGGER.exception("Failed to parse %s", MT_CONTROL_REQUEST)
            return
        if req is None:
            LOGGER.warning("%s missing RequestID; dropping", MT_CONTROL_REQUEST)
            return
        if req.controller_system_id is None:
            self._reject(
                ctx,
                req,
                reason="INVALID_INPUT_PARAMETER",
                description="ControlRequest missing Controller/SystemID",
            )
            return
        if req.is_release:
            self._release(ctx, req)
            return
        if req.is_acquire:
            self._acquire(ctx, req)
            return
        self._reject(
            ctx,
            req,
            reason="INVALID_INPUT_PARAMETER",
            description=f"Unsupported RequestType {req.request_type}",
        )

    def _acquire(self, ctx: IsolatorContext, req: ControlRequest) -> None:
        current = ctx.state.controller_system_id
        steal = req.request_type.upper() in {"STEAL", "ASSIGN_STEAL"}
        if current is not None and current != req.controller_system_id:
            if not steal:
                self._reject(
                    ctx,
                    req,
                    reason="CAPABILITY_UNAVAILABLE",
                    description="Control already assigned; use STEAL",
                )
                return
        ctx.state.controller_system_id = req.controller_system_id
        ctx.state.controller_service_id = req.controller_service_id
        ctx.state.control_type = req.control_type
        capability_id = req.capability_id or ctx.state.capability_id
        controllee = req.controllee_system_id or ctx.identity.uuid
        self._publish_status_ladder(ctx, req, approved=True)
        ctx.bus.publish(
            MT_CONTROL_ASSIGNMENT,
            build_control_assignment(
                ctx.identity,
                control_type=req.control_type,
                control_choice=req.control_choice,
                controller_system_id=req.controller_system_id,
                controller_service_id=req.controller_service_id,
                controllee_system_id=controllee,
                capability_id=capability_id,
                object_state="NEW",
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            ),
        )
        LOGGER.info(
            "%s ACQUIRE controller=%s → assignment",
            MT_CONTROL_REQUEST,
            req.controller_system_id.hex,
        )

    def _release(self, ctx: IsolatorContext, req: ControlRequest) -> None:
        current = ctx.state.controller_system_id
        if current is None:
            self._reject(
                ctx,
                req,
                reason="INVALID_INPUT_PARAMETER",
                description="No control assignment to release",
            )
            return
        if current != req.controller_system_id:
            self._reject(
                ctx,
                req,
                reason="INVALID_INPUT_PARAMETER",
                description="RELEASE controller does not own assignment",
            )
            return
        capability_id = req.capability_id or ctx.state.capability_id
        controllee = req.controllee_system_id or ctx.identity.uuid
        control_type = ctx.state.control_type or req.control_type
        self._publish_status_ladder(ctx, req, approved=True)
        ctx.bus.publish(
            MT_CONTROL_ASSIGNMENT,
            build_control_assignment(
                ctx.identity,
                control_type=control_type,
                control_choice=req.control_choice,
                controller_system_id=req.controller_system_id,
                controller_service_id=req.controller_service_id,
                controllee_system_id=controllee,
                capability_id=capability_id,
                object_state="REMOVED",
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            ),
        )
        ctx.state.controller_system_id = None
        ctx.state.controller_service_id = None
        ctx.state.control_type = None
        LOGGER.info("%s RELEASE → assignment REMOVED", MT_CONTROL_REQUEST)

    def _reject(
        self,
        ctx: IsolatorContext,
        req: ControlRequest,
        *,
        reason: str,
        description: str,
    ) -> None:
        ctx.bus.publish(
            MT_CONTROL_REQUEST_STATUS,
            build_control_request_status(
                ctx.identity,
                request_id=req.request_id,
                processing_state="REJECTED",
                approval_state="REJECTED",
                reason=reason,
                reason_description=description,
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            ),
        )
        LOGGER.info("%s → REJECTED (%s)", MT_CONTROL_REQUEST, reason)

    def _publish_status_ladder(
        self,
        ctx: IsolatorContext,
        req: ControlRequest,
        *,
        approved: bool,
    ) -> None:
        del approved
        schema = ctx.schema_version
        mode = ctx.message_mode
        for state in STATUS_LADDER:
            ctx.bus.publish(
                MT_CONTROL_REQUEST_STATUS,
                build_control_request_status(
                    ctx.identity,
                    request_id=req.request_id,
                    processing_state=state,
                    approval_state=_APPROVAL_FOR_LADDER.get(state, "PENDING"),
                    schema_version=schema,
                    mode=mode,
                ),
            )
