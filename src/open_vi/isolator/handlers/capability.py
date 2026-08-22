"""Inbound MA_FlightCapability → C2 designation overlay + readvertise."""

from __future__ import annotations

import logging

from open_vi.codec.capability import parse_flight_capability
from open_vi.codec.mts import MT_FLIGHT_CAPABILITY
from open_vi.codec.xmlutil import parse_header_system_id
from open_vi.isolator.context import IsolatorContext
from open_vi.isolator.publishers import advertise_control

LOGGER = logging.getLogger(__name__)


class CapabilityHandler:
    """Apply a C2 control-mode designation and republish the offer.

    Loopback of Isolator's own ``MA_FlightCapability`` is ignored
    (header SystemID matches identity). ``ObjectState`` ``REMOVED``
    clears the overlay.
    """

    inbound_mts = (MT_FLIGHT_CAPABILITY,)

    def handles(self, message_type: str) -> bool:
        return message_type == MT_FLIGHT_CAPABILITY

    def handle(self, message_type: str, xml: str, ctx: IsolatorContext) -> None:
        del message_type
        publisher = parse_header_system_id(xml)
        if publisher is not None and publisher == ctx.identity.uuid:
            return
        parsed = parse_flight_capability(xml)
        if (
            parsed.capability_id is not None
            and parsed.capability_id != ctx.state.capability_id
        ):
            LOGGER.info(
                "Ignored %s for other CapabilityID %s",
                MT_FLIGHT_CAPABILITY,
                parsed.capability_id.hex,
            )
            return
        if (parsed.object_state or "").upper() == "REMOVED":
            ctx.state.c2_capability_types = None
            LOGGER.info("Cleared C2 capability designation")
        else:
            ctx.state.c2_capability_types = parsed.capability_types
            LOGGER.info(
                "Applied C2 designation modes=%s",
                ",".join(parsed.capability_types) or "(none)",
            )
        advertise_control(ctx)
