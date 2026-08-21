"""Inbound MA_TaskCommand → MA_TaskCommandStatus + TaskStatus."""

from __future__ import annotations

import logging

from open_vi.codec.mts import (
    MT_TASK_COMMAND,
    MT_TASK_COMMAND_STATUS,
    MT_TASK_STATUS,
)
from open_vi.codec.task import (
    build_task_command_status,
    build_task_status,
    parse_task_commands,
)
from open_vi.isolator.context import IsolatorContext

LOGGER = logging.getLogger(__name__)

_EXECUTION_FOR_COMMAND = {
    "ACCEPTED": "EXECUTING",
    "CANCELED": "CANCELED",
    "REJECTED": "FAILED",
}


class TaskHandler:
    """Accept or cancel Task Capability commands; publish TaskStatus."""

    inbound_mts = (MT_TASK_COMMAND,)

    def handles(self, message_type: str) -> bool:
        return message_type == MT_TASK_COMMAND

    def handle(self, message_type: str, xml: str, ctx: IsolatorContext) -> None:
        del message_type
        try:
            commands = parse_task_commands(xml)
        except ValueError:
            LOGGER.exception("Failed to parse %s", MT_TASK_COMMAND)
            return
        if not commands:
            LOGGER.warning("%s contained no Command instances", MT_TASK_COMMAND)
            return
        for cmd in commands:
            if cmd.command_state == "CANCEL":
                processing = "CANCELED"
                if ctx.state.active_task_id == cmd.task_id:
                    ctx.state.active_task_id = None
            else:
                processing = "ACCEPTED"
                ctx.state.active_task_id = cmd.task_id
            ctx.bus.publish(
                MT_TASK_COMMAND_STATUS,
                build_task_command_status(
                    ctx.identity,
                    command_id=cmd.command_id,
                    processing_state=processing,
                    schema_version=ctx.schema_version,
                    mode=ctx.message_mode,
                ),
            )
            ctx.bus.publish(
                MT_TASK_STATUS,
                build_task_status(
                    ctx.identity,
                    task_id=cmd.task_id,
                    execution_state=_EXECUTION_FOR_COMMAND[processing],
                    schema_version=ctx.schema_version,
                    mode=ctx.message_mode,
                ),
            )
            LOGGER.info(
                "%s %s → %s task=%s",
                MT_TASK_COMMAND,
                cmd.command_id.hex,
                processing,
                cmd.task_id.hex,
            )
