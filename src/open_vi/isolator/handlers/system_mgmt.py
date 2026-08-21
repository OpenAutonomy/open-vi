"""Inbound MA_SystemManagementRequest (barometric / QNH)."""

from __future__ import annotations

import logging

from open_vi.codec.mts import MT_SYSTEM_MGMT_REQUEST, MT_SYSTEM_MGMT_STATUS
from open_vi.codec.status import parse_request_id
from open_vi.codec.system_mgmt import (
    build_system_management_request_status,
    parse_qnh_setting_kpa,
)
from open_vi.isolator.context import IsolatorContext

LOGGER = logging.getLogger(__name__)


class SystemManagementHandler:
    """Apply QNH / vehicle settings and reply COMPLETED."""

    inbound_mts = (MT_SYSTEM_MGMT_REQUEST,)

    def handles(self, message_type: str) -> bool:
        return message_type == MT_SYSTEM_MGMT_REQUEST

    def handle(self, message_type: str, xml: str, ctx: IsolatorContext) -> None:
        del message_type
        request_id = parse_request_id(xml)
        if request_id is None:
            LOGGER.warning("%s missing RequestID", MT_SYSTEM_MGMT_REQUEST)
            return
        qnh = parse_qnh_setting_kpa(xml)
        state = ctx.platform.apply_system_management(qnh_kpa=qnh)
        service = ctx.platform.get_service_status()
        ctx.bus.publish(
            MT_SYSTEM_MGMT_STATUS,
            build_system_management_request_status(
                ctx.identity,
                service,
                request_id=request_id,
                processing_state=state,
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            ),
        )
        LOGGER.info(
            "%s → %s (%s) qnh=%s",
            MT_SYSTEM_MGMT_REQUEST,
            MT_SYSTEM_MGMT_STATUS,
            state,
            qnh,
        )
