"""Inbound MA_Response → MA_SystemNotification (failsafe ack)."""

from __future__ import annotations

import logging

from open_vi.codec.mts import MT_MA_RESPONSE, MT_SYSTEM_NOTIFICATION
from open_vi.codec.notification import (
    build_system_notification,
    parse_response_id,
)
from open_vi.isolator.context import IsolatorContext

LOGGER = logging.getLogger(__name__)


class FailsafeHandler:
    """Ack MA failsafe Response with a CONFIRMED SystemNotification."""

    inbound_mts = (MT_MA_RESPONSE,)

    def handles(self, message_type: str) -> bool:
        return message_type == MT_MA_RESPONSE

    def handle(self, message_type: str, xml: str, ctx: IsolatorContext) -> None:
        del message_type
        response_id = parse_response_id(xml)
        if response_id is None:
            LOGGER.warning("%s missing ResponseID; dropping", MT_MA_RESPONSE)
            return
        service = ctx.platform.get_service_status()
        ctx.bus.publish(
            MT_SYSTEM_NOTIFICATION,
            build_system_notification(
                ctx.identity,
                associated_message_type="MA_RESPONSE",
                associated_id=response_id,
                service=service,
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            ),
        )
        LOGGER.info(
            "%s → %s response=%s",
            MT_MA_RESPONSE,
            MT_SYSTEM_NOTIFICATION,
            response_id.hex,
        )
