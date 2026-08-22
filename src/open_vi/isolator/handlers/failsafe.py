"""Inbound MA_Response → notify, store, and activate a failsafe plan."""

from __future__ import annotations

import logging

from open_vi.codec.mts import MT_MA_RESPONSE, MT_SYSTEM_NOTIFICATION
from open_vi.codec.notification import (
    build_system_notification,
    parse_ma_response,
)
from open_vi.isolator.context import IsolatorContext
from open_vi.isolator.handlers.route import activate_stored_route

LOGGER = logging.getLogger(__name__)


class FailsafeHandler:
    """Ack MA_Response; fly ActivatePlan when that route is stored."""

    inbound_mts = (MT_MA_RESPONSE,)

    def handles(self, message_type: str) -> bool:
        return message_type == MT_MA_RESPONSE

    def handle(self, message_type: str, xml: str, ctx: IsolatorContext) -> None:
        del message_type
        try:
            parsed = parse_ma_response(xml)
        except ValueError:
            LOGGER.exception("Failed to parse %s", MT_MA_RESPONSE)
            return
        if parsed is None:
            LOGGER.warning("%s missing ResponseID; dropping", MT_MA_RESPONSE)
            return
        if (parsed.object_state or "").upper() == "REMOVED":
            ctx.state.failsafe_response_id = None
            ctx.state.failsafe_route_id = None
            LOGGER.info(
                "%s REMOVED response=%s",
                MT_MA_RESPONSE,
                parsed.response_id.hex,
            )
            return
        ctx.state.failsafe_response_id = parsed.response_id
        ctx.state.failsafe_route_id = parsed.route_plan_id
        if parsed.route_plan_id is not None:
            result = activate_stored_route(ctx, parsed.route_plan_id)
            if result.processing_state == "ACCEPTED":
                LOGGER.info(
                    "%s ActivatePlan route=%s ACTIVATED",
                    MT_MA_RESPONSE,
                    parsed.route_plan_id.hex,
                )
            else:
                LOGGER.info(
                    "%s ActivatePlan route=%s not flown (%s)",
                    MT_MA_RESPONSE,
                    parsed.route_plan_id.hex,
                    result.reason_description or result.processing_state,
                )
        ctx.bus.publish(
            MT_SYSTEM_NOTIFICATION,
            build_system_notification(
                ctx.identity,
                associated_message_type="MA_RESPONSE",
                associated_id=parsed.response_id,
                service=ctx.platform.get_service_status(),
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            ),
        )
        LOGGER.info(
            "%s → %s response=%s",
            MT_MA_RESPONSE,
            MT_SYSTEM_NOTIFICATION,
            parsed.response_id.hex,
        )
