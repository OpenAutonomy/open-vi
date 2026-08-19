"""Inbound MA_FlightCommand → Status (+ Activity if ACCEPTED)."""

from __future__ import annotations

import logging
from uuid import uuid4

from open_vi.codec.command import (
    build_flight_activity,
    build_flight_command_status,
    parse_flight_commands,
)
from open_vi.codec.task import build_ma_task
from open_vi.domain import CommandResult, FlightCommandRequest, is_live_activity
from open_vi.isolator.context import IsolatorContext
from open_vi.isolator.handlers.task import MT_MA_TASK

LOGGER = logging.getLogger(__name__)

MT_FLIGHT_COMMAND = "MA_FlightCommand"
MT_FLIGHT_COMMAND_STATUS = "MA_FlightCommandStatus"
MT_FLIGHT_ACTIVITY = "MA_FlightActivity"


class FlightCommandHandler:
    """Handle Capability NEW/CANCEL and Activity UPDATE FlightCommands."""

    inbound_mts = (MT_FLIGHT_COMMAND,)

    def handles(self, message_type: str) -> bool:
        return message_type == MT_FLIGHT_COMMAND

    def handle(self, message_type: str, xml: str, ctx: IsolatorContext) -> None:
        del message_type  # protocol symmetry
        try:
            commands = parse_flight_commands(xml)
        except ValueError:
            LOGGER.exception("Failed to parse MA_FlightCommand")
            return
        if not commands:
            LOGGER.warning("MA_FlightCommand contained no Command instances")
            return
        for cmd in commands:
            result = self._submit(cmd, ctx)
            status_xml = build_flight_command_status(
                ctx.identity,
                command_id=cmd.command_id,
                result=result,
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            )
            ctx.bus.publish(MT_FLIGHT_COMMAND_STATUS, status_xml)
            LOGGER.info(
                "FlightCommand %s → %s",
                cmd.command_id.hex,
                result.processing_state,
            )
            if result.processing_state == "REJECTED":
                task_id = uuid4()
                ctx.bus.publish(
                    MT_MA_TASK,
                    build_ma_task(
                        ctx.identity,
                        task_id=task_id,
                        schema_version=ctx.schema_version,
                        mode=ctx.message_mode,
                    ),
                )
                LOGGER.info(
                    "Published suggest %s task=%s", MT_MA_TASK, task_id.hex
                )
            if (
                result.processing_state == "ACCEPTED"
                and result.activity_id is not None
            ):
                activity = ctx.platform.active_flight_activity()
                if activity is None:
                    continue
                activity_xml = build_flight_activity(
                    ctx.identity,
                    activity,
                    schema_version=ctx.schema_version,
                    mode=ctx.message_mode,
                    object_state="NEW" if result.new_activity else "UPDATED",
                )
                ctx.bus.publish(MT_FLIGHT_ACTIVITY, activity_xml)
                ctx.state.active_activity_id = activity.activity_id
                LOGGER.info(
                    "Published %s activity=%s",
                    MT_FLIGHT_ACTIVITY,
                    activity.activity_id.hex,
                )

    def _submit(
        self, cmd: FlightCommandRequest, ctx: IsolatorContext
    ) -> CommandResult:
        """Gate Capability NEW and Activity UPDATE, then call the platform."""
        reason = _command_reject_reason(cmd, ctx)
        if reason is not None:
            return CommandResult(
                processing_state="REJECTED",
                reason="INVALID_INPUT_PARAMETER",
                reason_description=reason,
            )
        return ctx.platform.submit_flight_command(cmd)


def _command_reject_reason(
    cmd: FlightCommandRequest, ctx: IsolatorContext
) -> str | None:
    """Return a reject description, or ``None`` if Isolator should submit."""
    if cmd.choice == "Activity":
        return _activity_reject_reason(cmd, ctx)
    if cmd.choice == "Capability":
        return _capability_reject_reason(cmd, ctx)
    return f"Unknown FlightCommand choice {cmd.choice}"


def _activity_reject_reason(
    cmd: FlightCommandRequest, ctx: IsolatorContext
) -> str | None:
    """Activity UPDATE must name the live activity."""
    if cmd.command_state != "UPDATE":
        return "Activity commands require CommandState UPDATE"
    if (
        cmd.activity_id is None
        or cmd.activity_id != ctx.state.active_activity_id
    ):
        return "Unknown or idle ActivityID"
    return None


def _capability_reject_reason(
    cmd: FlightCommandRequest, ctx: IsolatorContext
) -> str | None:
    """Capability NEW starts an activity; CANCEL stops one. No live replan."""
    if cmd.command_state == "CANCEL":
        return None
    if cmd.command_state != "NEW":
        return "Capability commands require CommandState NEW or CANCEL"
    if is_live_activity(ctx.platform.active_flight_activity()):
        return (
            "Capability NEW is not allowed while an activity is live; "
            "use Activity UPDATE"
        )
    return None
