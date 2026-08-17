"""Inbound QueryDataRequest → status ladder + native query outs."""

from __future__ import annotations

import logging
from uuid import uuid4

from open_vi.codec.capability import build_flight_capability
from open_vi.codec.query import (
    build_airfield_report,
    build_query_data_request_status,
    parse_query_kinds,
)
from open_vi.codec.route import (
    build_file_location_for_route,
    build_file_metadata_for_route,
)
from open_vi.codec.status import parse_request_id
from open_vi.isolator.compliance import status_ladder
from open_vi.isolator.context import IsolatorContext
from open_vi.isolator.handlers.route import (
    MT_FILE_LOCATION,
    MT_FILE_METADATA,
    MT_ROUTE_PLAN,
)

LOGGER = logging.getLogger(__name__)

MT_QUERY_DATA_REQUEST = "QueryDataRequest"
MT_QUERY_DATA_REQUEST_STATUS = "QueryDataRequestStatus"
MT_AIRFIELD_REPORT = "AirfieldReport"
MT_FLIGHT_CAPABILITY = "MA_FlightCapability"

_ALL_KINDS = ("capability", "route", "airfield")


class QueryHandler:
    """Reply to QueryDataRequest with status + native MTs."""

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
        kinds = parse_query_kinds(xml) or _ALL_KINDS
        self._publish_native(ctx, kinds)
        LOGGER.info(
            "%s → %s× %s kinds=%s request=%s",
            MT_QUERY_DATA_REQUEST,
            len(ladder),
            MT_QUERY_DATA_REQUEST_STATUS,
            ",".join(kinds),
            request_id.hex,
        )

    def _publish_native(
        self, ctx: IsolatorContext, kinds: tuple[str, ...]
    ) -> None:
        schema = ctx.schema_version
        mode = ctx.message_mode
        if "capability" in kinds:
            snap = ctx.platform.snapshot()
            ctx.bus.publish(
                MT_FLIGHT_CAPABILITY,
                build_flight_capability(
                    ctx.identity,
                    snap.offer,
                    capability_id=ctx.state.capability_id,
                    schema_version=schema,
                    mode=mode,
                ),
            )
        if "route" in kinds:
            for route_id in ctx.state.stored_route_ids:
                stored = ctx.routes.get(route_id)
                if stored is None:
                    continue
                file_metadata_id = uuid4()
                file_location_id = uuid4()
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
                ctx.bus.publish(MT_ROUTE_PLAN, stored.xml)
        if "airfield" in kinds:
            ctx.bus.publish(
                MT_AIRFIELD_REPORT,
                build_airfield_report(
                    ctx.identity,
                    schema_version=schema,
                    mode=mode,
                ),
            )
