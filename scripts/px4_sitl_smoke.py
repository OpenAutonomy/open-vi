#!/usr/bin/env python3
"""Live PX4 SITL smoke for Px4MavlinkAdapter (no ASB required)."""

from __future__ import annotations

import argparse
import sys
import time


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

    from open_vi.platform.px4 import Px4MavlinkAdapter

    print(f"Connecting to {args.mavlink_url} …")
    try:
        plat = Px4MavlinkAdapter(
            connection_url=args.mavlink_url,
            autoconnect=True,
            heartbeat_timeout_s=args.timeout,
        )
    except Exception as exc:  # pylint: disable=broad-exception-caught
        print(f"FAIL connect: {exc}", file=sys.stderr)
        return 1

    try:
        time.sleep(args.settle)
        snap = plat.snapshot()
        state = plat.get_vehicle_state()
        print(
            "snapshot:"
            f" available={snap.readiness.available}"
            f" availability={snap.readiness.availability}"
            f" reason={snap.readiness.reason}"
            f" modes={snap.offer.capability_types}"
        )
        print(
            "vehicle_state:"
            f" lat={state.latitude_deg:.6f}"
            f" lon={state.longitude_deg:.6f}"
            f" alt_m={state.altitude_m:.2f}"
            f" yaw_rad={state.yaw_rad:.3f}"
            f" fuel%={state.fuel_percent:.1f}"
        )
        if not snap.readiness.available:
            print("FAIL: link not AVAILABLE after settle", file=sys.stderr)
            return 2
        # Soft check: position may still be zero briefly on SIH.
        print("OK: PX4 SITL smoke passed (heartbeat + AVAILABLE)")
        return 0
    finally:
        plat.close()


if __name__ == "__main__":
    sys.exit(main())
