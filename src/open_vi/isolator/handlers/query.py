"""Inbound QueryDataRequest → Loose/Strict QueryDataRequestStatus."""

from __future__ import annotations

import logging

from open_vi.codec.query import build_query_data_request_status
from open_vi.codec.status import parse_request_id
from open_vi.isolator.compliance import status_ladder
from open_vi.isolator.context import IsolatorContext

LOGGER = logging.getLogger(__name__)

MT_QUERY_DATA_REQUEST = "QueryDataRequest"
MT_QUERY_DATA_REQUEST_STATUS = "QueryDataRequestStatus"


class QueryHandler:
    """Reply to QueryDataRequest with a compliance-mode status ladder."""

    inbound_mts = (MT_QUERY_DATA_REQUEST,)

    def handles(self, message_type: str) -> bool:
        return message_type == MT_QUERY_DATA_REQUEST

    def handle(self, message_type: str, xml: str, ctx: IsolatorContext) -> None:
        del message_type
        request_id = parse_request_id(xml)
        if request_id is None:
            LOGGER.warning("%s missing RequestID", MT_QUERY_DATA_REQUEST)
            return
        schema = ctx.schema_version
        mode = ctx.message_mode
        ladder = status_ladder(ctx)
        for state in ladder:
            ctx.bus.publish(
                MT_QUERY_DATA_REQUEST_STATUS,
                build_query_data_request_status(
                    ctx.identity,
                    request_id=request_id,
                    processing_state=state,
                    schema_version=schema,
                    mode=mode,
                ),
            )
        LOGGER.info(
            "%s → %s× %s request=%s",
            MT_QUERY_DATA_REQUEST,
            len(ladder),
            MT_QUERY_DATA_REQUEST_STATUS,
            request_id.hex,
        )
