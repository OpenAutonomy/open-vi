"""CLI entry for open-vi — launch the VI Isolator."""

from __future__ import annotations

import argparse
import logging
import os
import sys

from open_vi.asb import InMemoryAsb, StompActiveMqAdapter
from open_vi.codec.mts import MT_FLIGHT_CAPABILITY
from open_vi.config import AsbConfig, IsolatorConfig
from open_vi.isolator import Isolator
from open_vi.platform import make_platform

LOGGER = logging.getLogger("open_vi")


def _make_bus(memory: bool) -> InMemoryAsb | StompActiveMqAdapter:
    if memory:
        return InMemoryAsb()
    return StompActiveMqAdapter(AsbConfig.from_env())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="open-vi",
        description="A-GRA Vehicle Interface Isolator",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Debug logging",
    )
    parser.add_argument(
        "--memory",
        action="store_true",
        help="Use InMemoryAsb instead of STOMP",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Advertise once and exit (no tick loop)",
    )
    parser.add_argument(
        "--platform",
        choices=("stub", "px4"),
        default=os.environ.get("VI_PLATFORM", "stub"),
        help="Vehicle backend (default stub; or VI_PLATFORM)",
    )
    parser.add_argument(
        "--mavlink-url",
        default=os.environ.get("PX4_MAVLINK_URL"),
        help="PX4 MAVLink URL (default udpin:127.0.0.1:14540)",
    )
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    bus = _make_bus(args.memory)
    config = IsolatorConfig.from_env()
    platform = make_platform(
        args.platform,
        mavlink_url=args.mavlink_url,
        autoconnect=args.platform == "px4",
    )
    isolator = Isolator(bus, platform=platform, config=config)
    LOGGER.info("Platform=%s", args.platform)
    if args.once:
        bus.connect()
        try:
            isolator.advertise_once()
            if config.publish_status_package:
                isolator.publish_status_package_once()
            if config.publish_vehicle_state:
                isolator.publish_vehicle_state_once()
            if isinstance(bus, InMemoryAsb):
                bodies = bus.published.get(MT_FLIGHT_CAPABILITY)
                if bodies:
                    xml = bodies[0]
                    if not xml.endswith("\n"):
                        xml += "\n"
                    print(xml, end="")
        finally:
            bus.disconnect()
            platform.close()
        return 0

    LOGGER.info("Starting Isolator")
    try:
        isolator.run_forever()
    finally:
        platform.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
