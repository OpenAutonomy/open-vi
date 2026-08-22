"""Isolator lifecycle + edge-case coverage (attach, drops, contingencies)."""

from __future__ import annotations

import pytest

from open_vi.asb import InMemoryAsb, topic_dest
from open_vi.codec.mts import (
    MT_ACTIVATION_COMMAND,
    MT_CONTROL_REQUEST,
    MT_FLIGHT_CAPABILITY,
    MT_FLIGHT_COMMAND,
    MT_MA_RESPONSE,
    MT_MA_TASK,
    MT_QUERY_DATA_REQUEST,
    MT_QUERY_DATA_REQUEST_STATUS,
    MT_ROUTE_PLAN,
    MT_ROUTE_VALIDATION_COMMAND,
    MT_SERVICE_STATUS,
    MT_SERVICE_STATUS_DATA_REQUEST,
    MT_SUBSYSTEM_STATUS_DATA_REQUEST,
    MT_SYSTEM_MGMT_REQUEST,
    MT_SYSTEM_NOTIFICATION,
    MT_TASK_COMMAND,
)
from open_vi.codec.notification import build_sample_ma_response
from open_vi.codec.xmlutil import el, message_envelope, tostring
from open_vi.config import IsolatorConfig
from open_vi.isolator import Isolator
from open_vi.platform import StubPlatform

_EXPECTED_INBOUND = frozenset(
    {
        MT_FLIGHT_COMMAND,
        MT_SERVICE_STATUS,
        MT_SERVICE_STATUS_DATA_REQUEST,
        MT_SUBSYSTEM_STATUS_DATA_REQUEST,
        MT_ACTIVATION_COMMAND,
        MT_ROUTE_PLAN,
        MT_ROUTE_VALIDATION_COMMAND,
        MT_MA_RESPONSE,
        MT_SYSTEM_MGMT_REQUEST,
        MT_QUERY_DATA_REQUEST,
        MT_CONTROL_REQUEST,
        MT_FLIGHT_CAPABILITY,
        MT_TASK_COMMAND,
        MT_MA_TASK,
    }
)


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


def test_isolator_requires_platform() -> None:
    with pytest.raises(TypeError, match="platform"):
        Isolator(InMemoryAsb())  # type: ignore[call-arg]


def test_isolator_module_does_not_import_stub() -> None:
    import open_vi.isolator.executive as executive

    assert "StubPlatform" not in executive.__dict__


def test_inbound_mts_matches_default_handlers() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    assert frozenset(iso.inbound_mts) == _EXPECTED_INBOUND


def test_attach_subscribes_inbound_mts() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    for mt in _EXPECTED_INBOUND:
        assert topic_dest(mt) in bus.subscriptions
        assert f"{topic_dest(mt)}<None>" in bus.subscriptions
    assert bus.connected


def test_attach_is_idempotent() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    n_handlers = len(bus._handlers)  # pylint: disable=protected-access
    n_subs = len(bus.subscriptions)
    iso.attach()
    assert len(bus._handlers) == n_handlers  # pylint: disable=protected-access
    assert len(bus.subscriptions) == n_subs


def test_unknown_mt_logs_warning(caplog: pytest.LogCaptureFixture) -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    with caplog.at_level("WARNING"):
        iso.dispatch("TotallyUnknownMessage", "<root/>")
    assert any(
        "no handler for TotallyUnknownMessage" in r.message
        for r in caplog.records
    )


def test_failsafe_missing_response_id_drops() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    bare = tostring(
        message_envelope(
            "MA_Response",
            iso.identity,
            el("MessageData"),
            schema_version=iso.ctx.schema_version,
            mode=iso.ctx.message_mode,
            object_state="NEW",
        )
    )
    bus.publish(MT_MA_RESPONSE, bare)
    assert not bus.published.get(MT_SYSTEM_NOTIFICATION)


def test_failsafe_with_response_id_notifies() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    from uuid import uuid4

    response_id = uuid4()
    bus.publish(
        MT_MA_RESPONSE,
        build_sample_ma_response(iso.identity, response_id=response_id),
    )
    assert len(bus.published[MT_SYSTEM_NOTIFICATION]) == 1
    assert response_id.hex in bus.published[MT_SYSTEM_NOTIFICATION][-1].replace(
        "-", ""
    )


def test_query_missing_request_id_drops() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    bare = tostring(
        message_envelope(
            "QueryDataRequest",
            iso.identity,
            el("MessageData"),
            schema_version=iso.ctx.schema_version,
            mode=iso.ctx.message_mode,
        )
    )
    bus.publish(MT_QUERY_DATA_REQUEST, bare)
    assert not bus.published.get(MT_QUERY_DATA_REQUEST_STATUS)


def test_contingency_clear_readvertises() -> None:
    bus = InMemoryAsb()
    platform = StubPlatform()
    iso = Isolator(
        bus,
        platform=platform,
        config=IsolatorConfig(
            tick_republish_status=False,
            publish_vehicle_state=False,
            publish_status_package=False,
        ),
    )
    iso.attach()
    platform.inject_contingency("COLLISION_AVOIDANCE")
    iso.publish_capability_status_once()
    iso.publish_flight_capability_once()
    before = len(bus.published.get("MA_FlightCapability", ()))
    platform.inject_contingency("CLEAR")
    iso.advertise_once()
    after = len(bus.published.get("MA_FlightCapability", ()))
    assert after > before
    assert "AVAILABLE" in bus.published["MA_FlightCapabilityStatus"][-1]


def test_command_path_via_attach() -> None:
    """Flight command through public attach/dispatch (not protected wire)."""
    from uuid import uuid4

    from open_vi.codec.command import build_sample_waypoint_command
    from open_vi.codec.mts import MT_FLIGHT_ACTIVITY, MT_FLIGHT_COMMAND_STATUS

    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    iso.advertise_once()
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_waypoint_command(
            iso.identity,
            command_id=uuid4(),
            capability_id=iso.ctx.state.capability_id,
        ),
    )
    assert "ACCEPTED" in bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert bus.published[MT_FLIGHT_ACTIVITY]
