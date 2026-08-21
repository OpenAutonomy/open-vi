"""Isolator: ServiceStatus heartbeat + status data request exchange."""

from __future__ import annotations

from uuid import uuid4

from isolator_helpers import attach_isolator
from open_vi.asb import InMemoryAsb
from open_vi.codec.mts import (
    MT_FLIGHT_CAPABILITY_STATUS,
    MT_MA_FAULT,
    MT_SERVICE_STATUS,
    MT_SERVICE_STATUS_DATA_REQUEST,
    MT_SERVICE_STATUS_DATA_REQUEST_STATUS,
    MT_SUBSYSTEM_STATUS,
    MT_SUBSYSTEM_STATUS_DATA_REQUEST,
    MT_SUBSYSTEM_STATUS_DATA_REQUEST_STATUS,
)
from open_vi.codec.status import (
    build_sample_service_status,
    build_sample_service_status_data_request,
    build_sample_subsystem_status_data_request,
    build_service_status,
)
from open_vi.codec.xmlutil import local_name, parse_xml
from open_vi.config import IsolatorConfig
from open_vi.isolator import Isolator
from open_vi.platform import StubPlatform


def test_service_status_reply() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(
            tick_republish_status=False,
            publish_vehicle_state=False,
        ),
    )
    attach_isolator(iso)

    foreign_id = uuid4()
    bus.publish(
        MT_SERVICE_STATUS,
        build_sample_service_status(iso.identity, service_id=foreign_id),
    )

    replies = [
        xml
        for xml in bus.published[MT_SERVICE_STATUS]
        if platform.get_service_status().service_id.hex in xml.replace("-", "")
    ]
    assert replies
    assert local_name(parse_xml(replies[-1])) == "ServiceStatus"
    assert "NORMAL" in replies[-1]
    assert "TimeUp" in replies[-1]
    assert "open-vi" in replies[-1]


def test_service_status_data_request_bundle() -> None:
    bus = InMemoryAsb()
    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(
            tick_republish_status=False,
            publish_vehicle_state=False,
        ),
    )
    attach_isolator(iso)
    iso.advertise_once()

    request_id = uuid4()
    before = {
        MT_SERVICE_STATUS_DATA_REQUEST_STATUS: len(
            bus.published[MT_SERVICE_STATUS_DATA_REQUEST_STATUS]
        ),
        MT_FLIGHT_CAPABILITY_STATUS: len(
            bus.published[MT_FLIGHT_CAPABILITY_STATUS]
        ),
        MT_SUBSYSTEM_STATUS: len(bus.published[MT_SUBSYSTEM_STATUS]),
        MT_MA_FAULT: len(bus.published[MT_MA_FAULT]),
    }
    bus.publish(
        MT_SERVICE_STATUS_DATA_REQUEST,
        build_sample_service_status_data_request(
            iso.identity, request_id=request_id
        ),
    )

    assert (
        len(bus.published[MT_SERVICE_STATUS_DATA_REQUEST_STATUS])
        == before[MT_SERVICE_STATUS_DATA_REQUEST_STATUS] + 1
    )
    status = bus.published[MT_SERVICE_STATUS_DATA_REQUEST_STATUS][-1]
    assert "COMPLETED" in status
    assert request_id.hex in status.replace("-", "")
    assert "ServiceStatusData" in status

    assert (
        len(bus.published[MT_FLIGHT_CAPABILITY_STATUS])
        == before[MT_FLIGHT_CAPABILITY_STATUS] + 1
    )
    assert (
        len(bus.published[MT_SUBSYSTEM_STATUS])
        == before[MT_SUBSYSTEM_STATUS] + 1
    )
    subsystem = bus.published[MT_SUBSYSTEM_STATUS][-1]
    assert "OPERATE" in subsystem
    assert "About" in subsystem
    assert "open-vi-stub" in subsystem

    assert len(bus.published[MT_MA_FAULT]) == before[MT_MA_FAULT] + 1
    fault = bus.published[MT_MA_FAULT][-1]
    assert local_name(parse_xml(fault)) == "MA_Fault"
    assert "NO_FAULT" in fault
    assert "CLEARED" in fault


def test_subsystem_status_data_request_opt() -> None:
    bus = InMemoryAsb()
    iso = Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(
            tick_republish_status=False,
            publish_vehicle_state=False,
        ),
    )
    attach_isolator(iso)
    request_id = uuid4()
    bus.publish(
        MT_SUBSYSTEM_STATUS_DATA_REQUEST,
        build_sample_subsystem_status_data_request(
            iso.identity, request_id=request_id
        ),
    )
    reply = bus.published[MT_SUBSYSTEM_STATUS_DATA_REQUEST_STATUS][-1]
    assert "COMPLETED" in reply
    assert "SubsystemStatusData" in reply
    assert request_id.hex in reply.replace("-", "")


def test_own_service_status_does_not_loop() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(
            tick_republish_status=False,
            publish_vehicle_state=False,
        ),
    )
    attach_isolator(iso)
    ours = platform.get_service_status()
    bus.publish(
        MT_SERVICE_STATUS,
        build_service_status(iso.identity, ours),
    )
    # Only the injected message — no additional reply with same id.
    assert len(bus.published[MT_SERVICE_STATUS]) == 1
