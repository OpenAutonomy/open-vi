"""Inbound MA_Task and MA_TaskCommand."""

from __future__ import annotations

import logging
from xml.etree import ElementTree as ET

from open_vi.codec.mts import (
    MT_MA_TASK,
    MT_SYSTEM_NOTIFICATION,
    MT_TASK_COMMAND,
    MT_TASK_COMMAND_STATUS,
    MT_TASK_STATUS,
)
from open_vi.codec.notification import build_system_notification
from open_vi.codec.task import (
    build_task_command_status,
    build_task_status,
    parse_ma_task,
    parse_task_commands,
)
from open_vi.codec.xmlutil import parse_header_system_id
from open_vi.isolator.context import IsolatorContext

LOGGER = logging.getLogger(__name__)

_EXECUTION_FOR_COMMAND = {
    "ACCEPTED": "EXECUTING",
    "CANCELED": "CANCELED",
    "REJECTED": "FAILED",
}


class TaskHandler:
    """Ingest MA_Task, then accept or cancel Task Capability commands."""

    inbound_mts: tuple[str, ...] = (MT_TASK_COMMAND, MT_MA_TASK)

    def handles(self, message_type: str) -> bool:
        return message_type in self.inbound_mts

    def handle(self, message_type: str, xml: str, ctx: IsolatorContext) -> None:
        if message_type == MT_MA_TASK:
            self._ingest_task(xml, ctx)
            return
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

    def _notify_unusable(self, ctx: IsolatorContext, description: str) -> None:
        """Tell MA the MA_Task could not be stored.

        §1.2.2.5 has the VI answer an inbound ``MA_Task`` with
        ``MA_SystemNotification``. Dropping an unusable one silently
        leaves MA waiting for a response the interaction says it gets.

        This is the leg that can carry ``NotificationDetail``, which
        Table 1-10 requires: every ``CannotComplyEnum`` value states
        why something could not be done, so the acknowledgement of a
        task the VI *did* store has no truthful value to put there.
        There is no ``AssociatedID`` either -- a missing or unparseable
        TaskID is usually why we are here.
        """
        ctx.bus.publish(
            MT_SYSTEM_NOTIFICATION,
            build_system_notification(
                ctx.identity,
                associated_message_type="MA_TASK",
                associated_id=None,
                service=ctx.platform.get_service_status(),
                severity="CAUTION",
                detail_reason="INVALID_INPUT_PARAMETER",
                detail_description=description,
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            ),
        )
        LOGGER.info(
            "%s unusable → %s (%s)",
            MT_MA_TASK,
            MT_SYSTEM_NOTIFICATION,
            description,
        )

    def _ingest_task(self, xml: str, ctx: IsolatorContext) -> None:
        """Store an inbound MA_Task and notify; ignore Isolator loopback.

        Both parses are guarded, and for two exception types.
        ``parse_xml`` raises ``DefusedXmlException`` (a ``ValueError``)
        for entity and DTD tricks but ``ET.ParseError`` (a
        ``SyntaxError``) for XML that is merely malformed, so a
        ``ValueError`` guard alone leaves the commoner case to the
        dispatch loop -- which logs it and moves on, answering
        nothing. §1.2.2.5 says the VI answers an inbound MA_Task.
        """
        try:
            publisher = parse_header_system_id(xml)
            parsed = parse_ma_task(xml)
        except (ValueError, ET.ParseError):
            LOGGER.exception("Failed to parse %s", MT_MA_TASK)
            self._notify_unusable(ctx, "MA_Task did not parse")
            return
        if publisher is not None and publisher == ctx.identity.uuid:
            return
        if parsed is None:
            LOGGER.warning("%s missing TaskID; dropping", MT_MA_TASK)
            self._notify_unusable(ctx, "MA_Task missing TaskID")
            return
        if (parsed.object_state or "").upper() == "REMOVED":
            ctx.state.ingested_task_ids.discard(parsed.task_id)
            LOGGER.info("%s REMOVED task=%s", MT_MA_TASK, parsed.task_id.hex)
            return
        already = parsed.task_id in ctx.state.ingested_task_ids
        ctx.state.ingested_task_ids.add(parsed.task_id)
        if already:
            LOGGER.info(
                "Updated stored %s %s (no notify)",
                MT_MA_TASK,
                parsed.task_id.hex,
            )
            return
        ctx.bus.publish(
            MT_SYSTEM_NOTIFICATION,
            build_system_notification(
                ctx.identity,
                associated_message_type="MA_TASK",
                associated_id=parsed.task_id,
                service=ctx.platform.get_service_status(),
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            ),
        )
        LOGGER.info(
            "%s → %s task=%s",
            MT_MA_TASK,
            MT_SYSTEM_NOTIFICATION,
            parsed.task_id.hex,
        )
