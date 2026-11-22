"""PX4 mission upload, prefix skip, and MISSION start.

A second adapter can reuse :func:`advance_mission_waypoints` and
:func:`upload_waypoints` without the PX4 offboard path.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Callable

from open_vi.domain import Waypoint
from open_vi.platform.px4.link import MavlinkLink

LOGGER = logging.getLogger(__name__)

_EARTH_M = 6_378_137.0
# Adapter acceptance radius written to NAV_ACC_RAD / NAV_MC_ALT_RAD.
DEFAULT_PATH_CLEARANCE_M = 15.0


def horiz_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in meters."""
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    chord = (
        math.sin(dp / 2.0) ** 2
        + math.cos(p1) * math.cos(p2) * math.sin(dl / 2.0) ** 2
    )
    return 2.0 * _EARTH_M * math.asin(min(1.0, math.sqrt(chord)))


def enu_m(
    lat0: float, lon0: float, lat: float, lon: float
) -> tuple[float, float]:
    """East/north meters from ``(lat0, lon0)``."""
    lat0_rad = math.radians(lat0)
    east = math.radians(lon - lon0) * _EARTH_M * math.cos(lat0_rad)
    north = math.radians(lat - lat0) * _EARTH_M
    return east, north


def advance_mission_waypoints(
    waypoints: tuple[Waypoint, ...],
    here: tuple[float, float],
    *,
    capture_m: float = DEFAULT_PATH_CLEARANCE_M,
) -> tuple[Waypoint, ...]:
    """Drop prefix WPs already captured or behind the vehicle toward the goal.

    A replacement route often starts at the current pose, then a point
    behind the aircraft. Uploading that prefix makes PX4 turn around.
    Keep the goal.
    """
    if len(waypoints) <= 1:
        return waypoints
    goal = waypoints[-1]
    ge, gn = enu_m(here[0], here[1], goal.latitude_deg, goal.longitude_deg)
    kept = list(waypoints)
    while len(kept) > 1:
        we, wn = enu_m(
            here[0], here[1], kept[0].latitude_deg, kept[0].longitude_deg
        )
        captured = (
            horiz_m(
                here[0], here[1], kept[0].latitude_deg, kept[0].longitude_deg
            )
            < capture_m
        )
        behind = (we * ge + wn * gn) < 0.0
        if captured or behind:
            kept.pop(0)
            continue
        break
    return tuple(kept)


def remaining_waypoints(
    waypoints: tuple[Waypoint, ...],
    here: tuple[float, float] | None,
    *,
    capture_m: float,
) -> tuple[Waypoint, ...]:
    """Drop prefix waypoints already under or behind the vehicle."""
    if not waypoints or here is None:
        return waypoints
    return advance_mission_waypoints(waypoints, here, capture_m=capture_m)


def mission_rel_alt_m(
    altitude_m: float | None,
    *,
    home_hae_m: float | None,
    takeoff_alt_m: float,
) -> float:
    """A-GRA Point2D altitude is HAE; PX4 items are relative to home."""
    floor = takeoff_alt_m
    if altitude_m is None:
        return floor
    if home_hae_m is None:
        return max(floor, float(altitude_m))
    return max(floor, float(altitude_m) - home_hae_m)


def upload_waypoints(
    link: MavlinkLink,
    waypoints: tuple[Waypoint, ...],
    *,
    takeoff_alt_m: float,
    include_takeoff: bool,
    path_clearance_m: float,
) -> int:
    """Upload mission items. Returns last seq. Caller holds ``io_lock``."""
    # pylint: disable-next=import-outside-toplevel
    from pymavlink import mavutil

    conn = link.require_conn()
    mav = conn.mav
    target_system = conn.target_system
    target_component = conn.target_component
    # Standalone TAKEOFF mode sits at MIS_TAKEOFF_ALT. Embedding
    # NAV_TAKEOFF as item 0 then MISSION_START is the climb path.
    # Skip takeoff when already airborne.
    items: list[tuple[int, float, float, float]] = []
    if include_takeoff:
        first = waypoints[0]
        items.append(
            (
                mavutil.mavlink.MAV_CMD_NAV_TAKEOFF,
                first.latitude_deg,
                first.longitude_deg,
                float(takeoff_alt_m),
            )
        )
    for wp in waypoints:
        items.append(
            (
                mavutil.mavlink.MAV_CMD_NAV_WAYPOINT,
                wp.latitude_deg,
                wp.longitude_deg,
                float(wp.altitude_m if wp.altitude_m is not None else 50.0),
            )
        )
    if items:
        _, lat, lon, alt = items[-1]
        items.append((mavutil.mavlink.MAV_CMD_NAV_LOITER_UNLIM, lat, lon, alt))
    count = len(items)
    last_wp_seq = count - 2 if count >= 2 else count - 1
    mav.mission_count_send(target_system, target_component, count)
    frame = mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT
    waypoint_cmd = mavutil.mavlink.MAV_CMD_NAV_WAYPOINT
    for seq, (command, lat, lon, alt) in enumerate(items):
        msg = conn.recv_match(
            type=["MISSION_REQUEST", "MISSION_REQUEST_INT"],
            blocking=True,
            timeout=5.0,
        )
        if msg is None:
            raise TimeoutError(f"No MISSION_REQUEST for seq {seq}")
        is_last = seq == count - 1
        accept_m = path_clearance_m if command == waypoint_cmd else 0.0
        mav.mission_item_int_send(
            target_system,
            target_component,
            seq,
            frame,
            command,
            1 if seq == 0 else 0,  # current
            0 if is_last else 1,  # stop on the last item
            0,
            accept_m,
            0,
            0,
            int(lat * 1e7),
            int(lon * 1e7),
            alt,
        )
    ack = conn.recv_match(type="MISSION_ACK", blocking=True, timeout=5.0)
    if ack is None:
        raise TimeoutError("No MISSION_ACK")
    if int(getattr(ack, "type", -1)) != 0:
        ack_type = getattr(ack, "type", None)
        raise RuntimeError(f"MISSION_ACK type={ack_type}")
    first, last = waypoints[0], waypoints[-1]
    LOGGER.info(
        "Uploaded PX4 mission: %s + %s waypoints (last_seq=%s) "
        "first=%.5f,%.5f last=%.5f,%.5f alt=%.1fm",
        "takeoff" if include_takeoff else "no-takeoff",
        len(waypoints),
        last_wp_seq,
        first.latitude_deg,
        first.longitude_deg,
        last.latitude_deg,
        last.longitude_deg,
        float(last.altitude_m if last.altitude_m is not None else 50.0),
    )
    return last_wp_seq


def start_mission(
    link: MavlinkLink,
    *,
    wait_ack: Callable[[int, float], None],
) -> None:
    """Switch to MISSION and start. Caller must hold ``io_lock``."""
    # pylint: disable-next=import-outside-toplevel
    from pymavlink import mavutil

    conn = link.require_conn()
    if not link.set_mode("MISSION"):
        link.set_mode("AUTO.MISSION")
    # PX4 denies MISSION_START (COMMAND_ACK result=2) if it hasn't
    # finished the AUTO.MISSION nav_state transition yet -- the mode
    # switch above is itself a MAV_CMD_DO_SET_MODE that PX4 acks once
    # applied, so wait for that ack before racing MISSION_START in
    # behind it (verified live: sending them back to back denied
    # MISSION_START outright on the fixed-wing airframe).
    try:
        wait_ack(mavutil.mavlink.MAV_CMD_DO_SET_MODE, 2.0)
    except TimeoutError:
        LOGGER.warning("No ACK for DO_SET_MODE; continuing")
    conn.mav.command_long_send(
        conn.target_system,
        conn.target_component,
        mavutil.mavlink.MAV_CMD_MISSION_START,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
    )
    try:
        wait_ack(mavutil.mavlink.MAV_CMD_MISSION_START, 5.0)
    except TimeoutError:
        LOGGER.warning("No ACK for MISSION_START; continuing")
    LOGGER.info("PX4 mission started")


def execute_waypoint_following(
    link: MavlinkLink,
    waypoints: tuple[Waypoint, ...],
    *,
    here: tuple[float, float] | None,
    relative_alt_m: Callable[[], float],
    path_clearance_m: float,
    wait_ack: Callable[[int, float], None],
) -> int:
    """Upload mission and start MISSION mode. Returns last seq.

    The vehicle must already be armed and airborne -- VI no longer
    arms or launches PX4 (see ``docs/platforms/px4/README.md``); a
    human does that externally, and
    ``Px4MavlinkAdapter.snapshot()`` withholds AVAILABLE until
    telemetry confirms it. Raises if reached while not airborne --
    that indicates a readiness-gate bug, not a normal path.
    """
    rel_now = relative_alt_m()
    if rel_now < 2.0:
        raise RuntimeError(
            f"execute_waypoint_following called while not airborne "
            f"(relative_alt={rel_now:.1f}m); VI no longer arms or launches "
            f"PX4 -- this indicates a readiness-gate bug"
        )
    remaining = remaining_waypoints(waypoints, here, capture_m=path_clearance_m)
    if len(remaining) < len(waypoints):
        LOGGER.info(
            "PX4 skipped %d prefix WPs (kept %d, capture=%.0fm)",
            len(waypoints) - len(remaining),
            len(remaining),
            path_clearance_m,
        )
    rel_wps = tuple(
        Waypoint(
            latitude_deg=wp.latitude_deg,
            longitude_deg=wp.longitude_deg,
            altitude_m=rel_now,
        )
        for wp in remaining
    )
    with link.io_lock:
        link.hold()
        last_seq = upload_waypoints(
            link,
            rel_wps,
            takeoff_alt_m=rel_now,
            include_takeoff=False,
            path_clearance_m=path_clearance_m,
        )
        start_mission(link, wait_ack=wait_ack)
    LOGGER.info(
        "PX4 waypoint mission executing (%s WPs, last_seq=%s)",
        len(remaining),
        last_seq,
    )
    return last_seq
