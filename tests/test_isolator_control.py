"""Isolator: MA_ControlRequest → Status + Assignment / Unpair."""

from __future__ import annotations

from uuid import uuid4

from open_vi.asb import InMemoryAsb
from open_vi.codec.control import (
    build_sample_control_request,
    parse_control_request,
)
from open_vi.codec.mts import (
    MT_CONTROL_ASSIGNMENT,
    MT_CONTROL_REQUEST,
    MT_CONTROL_REQUEST_STATUS,
    MT_CONTROL_STATUS,
)
from open_vi.codec.xmlutil import local_name, parse_xml
from open_vi.config import IsolatorConfig
from open_vi.isolator import Isolator
from open_vi.platform import StubPlatform


def _iso(bus: InMemoryAsb) -> Isolator:
    return Isolator(
        bus,
        platform=StubPlatform(),
        config=IsolatorConfig(
            tick_republish_status=False,
            publish_vehicle_state=False,
            publish_status_package=False,
        ),
    )


def test_parse_sample_control_request() -> None:
    iso = _iso(InMemoryAsb())
    request_id = uuid4()
    controller = uuid4()
    xml = build_sample_control_request(
        iso.identity,
        request_id=request_id,
        controller_system_id=controller,
        capability_id=iso.ctx.state.capability_id,
    )
    req = parse_control_request(xml)
    assert req is not None
    assert req.request_id == request_id
    assert req.request_type == "ACQUIRE"
    assert req.controller_system_id == controller
    assert req.is_acquire


def test_acquire_publishes_status_and_assignment() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    request_id = uuid4()
    controller = uuid4()
    bus.publish(
        MT_CONTROL_REQUEST,
        build_sample_control_request(
            iso.identity,
            request_id=request_id,
            controller_system_id=controller,
            capability_id=iso.ctx.state.capability_id,
        ),
    )
    statuses = list(bus.published[MT_CONTROL_REQUEST_STATUS])
    assert len(statuses) == 3
    assert "QUEUED" in statuses[0]
    assert "PROCESSING" in statuses[1]
    assert "PENDING" in statuses[1]
    assert "COMPLETED" in statuses[2]
    assert "APPROVED" in statuses[2]
    assert request_id.hex in statuses[2].replace("-", "")
    assignment = bus.published[MT_CONTROL_ASSIGNMENT][-1]
    assert local_name(parse_xml(assignment)) == "MA_ControlAssignment"
    assert "CAPABILITY_PRIMARY" in assignment
    assert controller.hex in assignment.replace("-", "")
    assert iso.ctx.state.controller_system_id == controller


def test_second_acquire_without_steal_rejected() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    first = uuid4()
    second = uuid4()
    bus.publish(
        MT_CONTROL_REQUEST,
        build_sample_control_request(
            iso.identity,
            request_id=uuid4(),
            controller_system_id=first,
        ),
    )
    bus.publish(
        MT_CONTROL_REQUEST,
        build_sample_control_request(
            iso.identity,
            request_id=uuid4(),
            controller_system_id=second,
        ),
    )
    last = bus.published[MT_CONTROL_REQUEST_STATUS][-1]
    assert "REJECTED" in last
    assert iso.ctx.state.controller_system_id == first


def test_steal_replaces_controller() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    first = uuid4()
    second = uuid4()
    bus.publish(
        MT_CONTROL_REQUEST,
        build_sample_control_request(
            iso.identity,
            request_id=uuid4(),
            controller_system_id=first,
        ),
    )
    bus.publish(
        MT_CONTROL_REQUEST,
        build_sample_control_request(
            iso.identity,
            request_id=uuid4(),
            request_type="STEAL",
            controller_system_id=second,
        ),
    )
    assert iso.ctx.state.controller_system_id == second
    assert "APPROVED" in bus.published[MT_CONTROL_REQUEST_STATUS][-1]


def test_release_unpairs() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    controller = uuid4()
    bus.publish(
        MT_CONTROL_REQUEST,
        build_sample_control_request(
            iso.identity,
            request_id=uuid4(),
            controller_system_id=controller,
        ),
    )
    bus.publish(
        MT_CONTROL_REQUEST,
        build_sample_control_request(
            iso.identity,
            request_id=uuid4(),
            request_type="RELEASE",
            controller_system_id=controller,
        ),
    )
    assert iso.ctx.state.controller_system_id is None
    assignment = bus.published[MT_CONTROL_ASSIGNMENT][-1]
    assert "REMOVED" in assignment
    assert "APPROVED" in bus.published[MT_CONTROL_REQUEST_STATUS][-1]


def test_missing_request_id_drops() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    from open_vi.codec.xmlutil import el, message_envelope, tostring

    bare = tostring(
        message_envelope(
            "MA_ControlRequest",
            iso.identity,
            el("MessageData"),
            schema_version=iso.ctx.schema_version,
            mode=iso.ctx.message_mode,
        )
    )
    bus.publish(MT_CONTROL_REQUEST, bare)
    assert not bus.published.get(MT_CONTROL_REQUEST_STATUS)


def test_control_status_idle_has_no_secondary() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    iso.publish_status_package_once()
    status = bus.published[MT_CONTROL_STATUS][-1]
    assert "PrimaryController" in status
    assert "SecondaryController" not in status


def test_control_status_secondary_after_acquire() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    controller = uuid4()
    service = uuid4()
    bus.publish(
        MT_CONTROL_REQUEST,
        build_sample_control_request(
            iso.identity,
            request_id=uuid4(),
            controller_system_id=controller,
            controller_service_id=service,
        ),
    )
    iso.publish_status_package_once()
    status = bus.published[MT_CONTROL_STATUS][-1]
    assert "SecondaryController" in status
    assert controller.hex in status.replace("-", "")
    assert service.hex in status.replace("-", "")


def test_control_status_no_secondary_without_service_id() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    bus.publish(
        MT_CONTROL_REQUEST,
        build_sample_control_request(
            iso.identity,
            request_id=uuid4(),
            controller_system_id=uuid4(),
        ),
    )
    iso.publish_status_package_once()
    assert "SecondaryController" not in bus.published[MT_CONTROL_STATUS][-1]


def test_control_status_clears_secondary_on_release() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    controller = uuid4()
    service = uuid4()
    bus.publish(
        MT_CONTROL_REQUEST,
        build_sample_control_request(
            iso.identity,
            request_id=uuid4(),
            controller_system_id=controller,
            controller_service_id=service,
        ),
    )
    bus.publish(
        MT_CONTROL_REQUEST,
        build_sample_control_request(
            iso.identity,
            request_id=uuid4(),
            request_type="RELEASE",
            controller_system_id=controller,
            controller_service_id=service,
        ),
    )
    iso.publish_status_package_once()
    assert "SecondaryController" not in bus.published[MT_CONTROL_STATUS][-1]
