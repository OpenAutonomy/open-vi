"""Isolator: inbound MA_FlightCapability redacts advertised modes."""

from __future__ import annotations

from uuid import uuid4

from open_vi.asb import InMemoryAsb
from open_vi.codec.capability import (
    build_flight_capability,
    parse_flight_capability,
)
from open_vi.codec.command import build_sample_hsa_csa_command
from open_vi.codec.mts import (
    MT_FLIGHT_CAPABILITY,
    MT_FLIGHT_COMMAND,
    MT_FLIGHT_COMMAND_STATUS,
    MT_QUERY_DATA_REQUEST,
)
from open_vi.codec.query import build_sample_query_data_request
from open_vi.config import IsolatorConfig
from open_vi.domain import ControlOffer, redact_control_offer
from open_vi.identity import SystemIdentity
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


def _c2_capability(
    iso: Isolator,
    *,
    types: tuple[str, ...],
    capability_id=None,
    object_state: str = "NEW",
) -> bytes:
    return build_flight_capability(
        SystemIdentity.named("c2-designator"),
        ControlOffer(capability_types=types),
        capability_id=capability_id or iso.ctx.state.capability_id,
        object_state=object_state,
        schema_version=iso.ctx.schema_version,
        mode=iso.ctx.message_mode,
    )


def test_parse_flight_capability_types() -> None:
    iso = _iso(InMemoryAsb())
    parsed = parse_flight_capability(
        _c2_capability(iso, types=("WAYPOINT_FOLLOWING", "HSA_CSA"))
    )
    assert parsed.capability_types == ("WAYPOINT_FOLLOWING", "HSA_CSA")
    assert parsed.capability_id == iso.ctx.state.capability_id


def test_redact_offer_keeps_platform_order() -> None:
    offer = ControlOffer()
    redacted = redact_control_offer(offer, ("CURVE_FOLLOWING", "HSA_CSA"))
    assert redacted.capability_types == ("HSA_CSA", "CURVE_FOLLOWING")
    assert redacted.waypoint_profile is None


def test_own_advertise_after_attach_does_not_loop() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    iso.advertise_once()
    assert len(bus.published[MT_FLIGHT_CAPABILITY]) == 1
    assert iso.ctx.state.c2_capability_types is None


def test_c2_designation_redacts_advertised_modes() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    bus.publish(
        MT_FLIGHT_CAPABILITY,
        _c2_capability(iso, types=("WAYPOINT_FOLLOWING",)),
    )
    assert iso.ctx.state.c2_capability_types == ("WAYPOINT_FOLLOWING",)
    advertised = bus.published[MT_FLIGHT_CAPABILITY][-1]
    assert "WAYPOINT_FOLLOWING" in advertised
    assert "HSA_CSA" not in advertised
    assert "CURVE_FOLLOWING" not in advertised


def test_redacted_mode_command_is_rejected() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    bus.publish(
        MT_FLIGHT_CAPABILITY,
        _c2_capability(iso, types=("WAYPOINT_FOLLOWING",)),
    )
    bus.publish(
        MT_FLIGHT_COMMAND,
        build_sample_hsa_csa_command(
            iso.identity,
            command_id=uuid4(),
            capability_id=iso.ctx.state.capability_id,
        ),
    )
    status = bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
    assert "REJECTED" in status
    assert "C2 designation" in status


def test_query_capability_uses_redacted_offer() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    bus.publish(
        MT_FLIGHT_CAPABILITY,
        _c2_capability(iso, types=("WAYPOINT_FOLLOWING",)),
    )
    before = len(bus.published[MT_FLIGHT_CAPABILITY])
    bus.publish(
        MT_QUERY_DATA_REQUEST,
        build_sample_query_data_request(iso.identity, request_id=uuid4()),
    )
    queried = bus.published[MT_FLIGHT_CAPABILITY][before]
    assert "WAYPOINT_FOLLOWING" in queried
    assert "HSA_CSA" not in queried


def test_foreign_capability_id_is_ignored() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    bus.publish(
        MT_FLIGHT_CAPABILITY,
        _c2_capability(
            iso, types=("WAYPOINT_FOLLOWING",), capability_id=uuid4()
        ),
    )
    assert iso.ctx.state.c2_capability_types is None
    assert len(bus.published[MT_FLIGHT_CAPABILITY]) == 1


def test_removed_designation_clears_overlay() -> None:
    bus = InMemoryAsb()
    iso = _iso(bus)
    iso.attach()
    bus.publish(
        MT_FLIGHT_CAPABILITY,
        _c2_capability(iso, types=("WAYPOINT_FOLLOWING",)),
    )
    bus.publish(
        MT_FLIGHT_CAPABILITY,
        _c2_capability(
            iso, types=("WAYPOINT_FOLLOWING",), object_state="REMOVED"
        ),
    )
    assert iso.ctx.state.c2_capability_types is None
    restored = bus.published[MT_FLIGHT_CAPABILITY][-1]
    assert "HSA_CSA" in restored
    assert "WAYPOINT_FOLLOWING" in restored
    assert "CURVE_FOLLOWING" in restored
