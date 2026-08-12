"""Inbound ServiceStatus / status data requests (heartbeat exchange)."""

from __future__ import annotations

import logging

from open_vi.codec.capability import build_flight_capability_status
from open_vi.codec.status import (
    build_ma_fault,
    build_service_status,
    build_service_status_data_request_status,
    build_subsystem_status,
    build_subsystem_status_data_request_status,
    parse_request_id,
    parse_service_id,
)
from open_vi.isolator.context import IsolatorContext

LOGGER = logging.getLogger(__name__)

MT_SERVICE_STATUS = "ServiceStatus"
MT_SERVICE_STATUS_DATA_REQUEST = "ServiceStatusDataRequest"
MT_SERVICE_STATUS_DATA_REQUEST_STATUS = "ServiceStatusDataRequestStatus"
MT_SUBSYSTEM_STATUS = "SubsystemStatus"
MT_SUBSYSTEM_STATUS_DATA_REQUEST = "SubsystemStatusDataRequest"
MT_SUBSYSTEM_STATUS_DATA_REQUEST_STATUS = "SubsystemStatusDataRequestStatus"
MT_MA_FAULT = "MA_Fault"
MT_FLIGHT_CAPABILITY_STATUS = "MA_FlightCapabilityStatus"

_HANDLED = {
    MT_SERVICE_STATUS,
    MT_SERVICE_STATUS_DATA_REQUEST,
    MT_SUBSYSTEM_STATUS_DATA_REQUEST,
}


class HeartbeatHandler:
    """Reply to ServiceStatus and Service/Subsystem status data requests."""

    inbound_mts = (
        MT_SERVICE_STATUS,
        MT_SERVICE_STATUS_DATA_REQUEST,
        MT_SUBSYSTEM_STATUS_DATA_REQUEST,
    )

    def handles(self, message_type: str) -> bool:
        return message_type in _HANDLED

    def handle(self, message_type: str, xml: str, ctx: IsolatorContext) -> None:
        if message_type == MT_SERVICE_STATUS:
            self._on_service_status(xml, ctx)
        elif message_type == MT_SERVICE_STATUS_DATA_REQUEST:
            self._on_service_status_data_request(xml, ctx)
        elif message_type == MT_SUBSYSTEM_STATUS_DATA_REQUEST:
            self._on_subsystem_status_data_request(xml, ctx)

    def _on_service_status(self, xml: str, ctx: IsolatorContext) -> None:
        ours = ctx.platform.get_service_status()
        inbound_id = parse_service_id(xml)
        if inbound_id is not None and inbound_id == ours.service_id:
            # Ignore loopback of our own heartbeat publish.
            return
        ctx.bus.publish(
            MT_SERVICE_STATUS,
            build_service_status(
                ctx.identity,
                ours,
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            ),
        )
        LOGGER.info("Replied with %s", MT_SERVICE_STATUS)

    def _on_service_status_data_request(
        self, xml: str, ctx: IsolatorContext
    ) -> None:
        request_id = parse_request_id(xml)
        if request_id is None:
            LOGGER.warning("ServiceStatusDataRequest missing RequestID")
            return
        service = ctx.platform.get_service_status()
        subsystem = ctx.platform.get_subsystem_status()
        faults = ctx.platform.get_faults()
        snap = ctx.platform.snapshot()

        ctx.bus.publish(
            MT_SERVICE_STATUS_DATA_REQUEST_STATUS,
            build_service_status_data_request_status(
                ctx.identity,
                service,
                request_id=request_id,
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            ),
        )
        ctx.bus.publish(
            MT_FLIGHT_CAPABILITY_STATUS,
            build_flight_capability_status(
                ctx.identity,
                snap.readiness,
                capability_id=ctx.state.capability_id,
                capability_label=snap.offer.capability_label,
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            ),
        )
        ctx.bus.publish(
            MT_SUBSYSTEM_STATUS,
            build_subsystem_status(
                ctx.identity,
                subsystem,
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            ),
        )
        ctx.bus.publish(
            MT_MA_FAULT,
            build_ma_fault(
                ctx.identity,
                faults,
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            ),
        )
        LOGGER.info(
            "ServiceStatusDataRequest → RequestStatus, "
            "FlightCapabilityStatus, SubsystemStatus, Fault"
        )

    def _on_subsystem_status_data_request(
        self, xml: str, ctx: IsolatorContext
    ) -> None:
        request_id = parse_request_id(xml)
        if request_id is None:
            LOGGER.warning("SubsystemStatusDataRequest missing RequestID")
            return
        subsystem = ctx.platform.get_subsystem_status()
        ctx.bus.publish(
            MT_SUBSYSTEM_STATUS_DATA_REQUEST_STATUS,
            build_subsystem_status_data_request_status(
                ctx.identity,
                subsystem,
                request_id=request_id,
                schema_version=ctx.schema_version,
                mode=ctx.message_mode,
            ),
        )
        LOGGER.info("Replied with %s", MT_SUBSYSTEM_STATUS_DATA_REQUEST_STATUS)
