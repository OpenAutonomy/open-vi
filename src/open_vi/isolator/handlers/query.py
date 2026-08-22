"""Inbound QueryDataRequest → status ladder + native query outs."""

from __future__ import annotations

import hashlib
import logging
from uuid import UUID, uuid4

from open_vi.codec.capability import build_flight_capability
from open_vi.codec.mts import (
    MT_AIRFIELD_REPORT,
    MT_FILE_LOCATION,
    MT_FILE_METADATA,
    MT_FLIGHT_CAPABILITY,
    MT_QUERY_DATA_REQUEST,
    MT_QUERY_DATA_REQUEST_STATUS,
    MT_ROUTE_PLAN,
)
from open_vi.codec.query import (
    build_airfield_report,
    build_query_data_request_status,
    parse_query_request,
)
from open_vi.codec.route import (
    build_file_location_for_route,
    build_file_metadata_for_route,
)
from open_vi.codec.status import parse_request_id
from open_vi.isolator.context import IsolatorContext
from open_vi.isolator.handlers.base import STATUS_LADDER

LOGGER = logging.getLogger(__name__)

_ALL_KINDS = ("capability", "route", "airfield")
_CHECKSUM_REASON = "INVALID_INPUT_PARAMETER"
_CHECKSUM_DESCRIPTION = "Stored MA_RoutePlan checksum mismatch"


class QueryHandler:
    """Reply to QueryDataRequest with status + native MTs or IDs."""

    inbound_mts = (MT_QUERY_DATA_REQUEST,)

    def handles(self, message_type: str) -> bool:
        return message_type == MT_QUERY_DATA_REQUEST

    def handle(self, message_type: str, xml: str, ctx: IsolatorContext) -> None:
        del message_type
        request_id = parse_request_id(xml)
        if request_id is None:
            LOGGER.warning("%s missing RequestID", MT_QUERY_DATA_REQUEST)
            return
        parsed = parse_query_request(xml)
        kinds = parsed.kinds or _ALL_KINDS
        result_ids, fail_reason, fail_desc = self._collect(ctx, kinds)
        schema = ctx.schema_version
        mode = ctx.message_mode
        if fail_reason is not None:
            ladder = ("QUEUED", "PROCESSING", "FAILED")
        else:
            ladder = STATUS_LADDER
        for state in ladder:
            ids = result_ids if state == "COMPLETED" else ()
            ctx.bus.publish(
                MT_QUERY_DATA_REQUEST_STATUS,
                build_query_data_request_status(
                    ctx.identity,
                    request_id=request_id,
                    processing_state=state,
                    result_ids=ids,
                    reason=fail_reason if state == "FAILED" else None,
                    reason_description=(
                        fail_desc if state == "FAILED" else None
                    ),
                    schema_version=schema,
                    mode=mode,
                ),
            )
        if fail_reason is None and not parsed.identifiers_only:
            self._publish_native(ctx, kinds)
        LOGGER.info(
            "%s → %s× %s kinds=%s ids_only=%s request=%s",
            MT_QUERY_DATA_REQUEST,
            len(ladder),
            MT_QUERY_DATA_REQUEST_STATUS,
            ",".join(kinds),
            parsed.identifiers_only,
            request_id.hex,
        )

    def _collect(
        self, ctx: IsolatorContext, kinds: tuple[str, ...]
    ) -> tuple[tuple[tuple[UUID, str], ...], str | None, str | None]:
        """Matching IDs, or a checksum fail reason."""
        collected: list[tuple[UUID, str]] = []
        if "capability" in kinds:
            collected.append((ctx.state.capability_id, "capability"))
        if "route" in kinds:
            for route_id in ctx.routes.ingested_ids():
                stored = ctx.routes.get(route_id)
                if stored is None:
                    continue
                digest = hashlib.sha256(stored.xml.encode("utf-8")).hexdigest()
                if digest != stored.sha256_hex:
                    return (), _CHECKSUM_REASON, _CHECKSUM_DESCRIPTION
                collected.append((route_id, "route-plan"))
        if "airfield" in kinds:
            collected.append((ctx.identity.uuid, "home-field"))
        return tuple(collected), None, None

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
            for route_id in ctx.routes.ingested_ids():
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
                    airfield_id=ctx.identity.uuid,
                    schema_version=schema,
                    mode=mode,
                ),
            )
