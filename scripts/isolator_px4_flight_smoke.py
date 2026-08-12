#!/usr/bin/env python3
"""Isolator + PX4 SITL: MA_FlightCommand → Status/Activity + climb.

Uses an in-process InMemoryAsb (same process as Isolator). Requires a live
PX4 SITL on the MAVLink URL (default udpin:127.0.0.1:14540).
"""

from __future__ import annotations

import argparse
import sys
import time
from uuid import uuid4


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--mavlink-url",
        default="udpin:127.0.0.1:14540",
        help="MAVLink connection URL",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument(
        "--settle",
        type=float,
        default=3.0,
        help="Seconds to wait for telemetry after heartbeat",
    )
    args = parser.parse_args()

    from open_vi.asb import InMemoryAsb
    from open_vi.codec.command import build_sample_waypoint_command
    from open_vi.codec.xmlutil import local_name, parse_xml
    from open_vi.config import IsolatorConfig
    from open_vi.isolator import Isolator
    from open_vi.isolator.handlers.flight_command import (
        MT_FLIGHT_ACTIVITY,
        MT_FLIGHT_COMMAND,
        MT_FLIGHT_COMMAND_STATUS,
    )
    from open_vi.platform import Waypoint
    from open_vi.platform.px4 import Px4MavlinkAdapter

    print(f"Connecting PX4 at {args.mavlink_url} …")
    try:
        plat = Px4MavlinkAdapter(
            connection_url=args.mavlink_url,
            autoconnect=True,
            heartbeat_timeout_s=args.timeout,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"FAIL connect: {exc}", file=sys.stderr)
        return 1

    bus = InMemoryAsb()
    iso = Isolator(
        bus,
        platform=plat,
        config=IsolatorConfig(tick_republish_status=False),
    )
    try:
        iso.attach()
        time.sleep(args.settle)
        snap = plat.snapshot()
        if not snap.readiness.available:
            print("FAIL: PX4 link not AVAILABLE after settle", file=sys.stderr)
            return 2
        iso.advertise_once()

        before_rel = plat._relative_alt_m()  # pylint: disable=protected-access
        print(f"before: available rel_alt={before_rel:.1f}m")

        # SIH default home ≈ Zurich; keep WPs nearby.
        waypoints = (
            Waypoint(47.3980, 8.5460, 30.0),
            Waypoint(47.3985, 8.5465, 30.0),
        )
        command_id = uuid4()
        xml = build_sample_waypoint_command(
            iso.identity,
            command_id=command_id,
            capability_id=iso.ctx.state.capability_id,
            waypoints=waypoints,
        )
        print("Publishing MA_FlightCommand (WAYPOINT_FOLLOWING) …")
        t0 = time.monotonic()
        bus.publish(MT_FLIGHT_COMMAND, xml)
        elapsed = time.monotonic() - t0

        if MT_FLIGHT_COMMAND_STATUS not in bus.published:
            print("FAIL: no MA_FlightCommandStatus", file=sys.stderr)
            return 3
        status = bus.published[MT_FLIGHT_COMMAND_STATUS][-1]
        if local_name(parse_xml(status)) != "MA_FlightCommandStatus":
            print("FAIL: unexpected status root", file=sys.stderr)
            return 3
        if "ACCEPTED" not in status:
            print(
                f"FAIL: not ACCEPTED ({elapsed:.1f}s)\n{status}",
                file=sys.stderr,
            )
            return 3
        print(f"status: ACCEPTED ({elapsed:.1f}s)")

        if MT_FLIGHT_ACTIVITY not in bus.published:
            print("FAIL: no MA_FlightActivity", file=sys.stderr)
            return 4
        activity = bus.published[MT_FLIGHT_ACTIVITY][-1]
        if "ACTIVE_UNCONSTRAINED" not in activity:
            print("FAIL: activity not ACTIVE_UNCONSTRAINED", file=sys.stderr)
            return 4
        print("activity: ACTIVE_UNCONSTRAINED")

        time.sleep(3.0)
        after_rel = plat._relative_alt_m()  # pylint: disable=protected-access
        state = plat.get_vehicle_state()
        print(
            f"after: rel_alt={after_rel:.1f}m"
            f" alt_m={state.altitude_m:.1f}"
            f" lat={state.latitude_deg:.5f} lon={state.longitude_deg:.5f}"
        )
        if after_rel < 5.0:
            print("FAIL: vehicle did not climb above 5m AGL", file=sys.stderr)
            return 5
        print("OK: Isolator + PX4 FlightCommand smoke passed")
        return 0
    finally:
        iso.stop()
        plat.close()


if __name__ == "__main__":
    sys.exit(main())
