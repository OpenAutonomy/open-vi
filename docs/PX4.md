# PX4

`Px4MavlinkAdapter` is the PX4 / SITL backend behind `PlatformPort`. It
speaks MAVLink (pymavlink) and returns the same `open_vi.domain` types as
Stub. Isolator and codec never import MAVLink. The port is in
[PLATFORM.md](PLATFORM.md).

```mermaid
flowchart LR
  Iso["Isolator"]
  Port["PlatformPort"]
  Px4["Px4MavlinkAdapter"]
  SITL["PX4 SITL"]

  Iso --> Port
  Port --> Px4
  Px4 <-->|"MAVLink UDP"| SITL
```

The adapter does telemetry and `WAYPOINT_FOLLOWING`. Arm, takeoff, and
mission start stay inside the adapter. Mission Autonomy sends
`MA_FlightCommand`, not UCI arm or takeoff. Capability NEW starts a
mission when idle. Activity UPDATE is the replan: it reuses the airborne
replace (hold, drop prefix waypoints, skip takeoff) and keeps the live
`activity_id`. A second Capability NEW while airborne is rejected.

Before upload, the adapter checks the path against a relative-altitude
envelope (default 10–500 m AGL; `PX4_MIN_REL_ALT_M` /
`PX4_MAX_REL_ALT_M`). Rejects use Volume `ValidationResult`
(`INVALID_WAYPOINT`, `PERFORMANCE_LIMIT_EXCEEDED`,
`CAPABILITY_NOT_SUPPORTED`). The same limits are advertised on
`MA_FlightCapability` as `WaypointFollowingPerformanceProfile` (HAE
once home is known, otherwise AGL). `apply_system_management` writes
`SENS_BARO_QNH` and the local TSPI snapshot.

Isolator owns the route ladder; ACTIVATE does not push a stored
`MA_RoutePlan` to the vehicle.

`import open_vi.platform` does not load this module. `make_platform("px4")`
imports it.

## Install and SITL

Install pymavlink (`pip install -e ".[px4]"`; `.[dev]` already includes
it). Start PX4 SITL so MAVLink is on UDP 14540:

```bash
docker run -d --name open-vi-px4-sitl \
  -p 14550:14550/udp -p 14540:14540/udp \
  px4io/px4-sitl:latest
```

The image home is about 47.40°N, 8.55°E. Then:

```bash
open-vi --platform px4
```

`--platform px4` and `VI_PLATFORM=px4` select the backend. The MAVLink URL
defaults to `udpin:127.0.0.1:14540` (`--mavlink-url` or `PX4_MAVLINK_URL`).
Acceptance radius defaults to 15 m (`path_clearance_m` or
`PX4_PATH_CLEARANCE_M`). That is this adapter's capture disk, not a
shared Mission Autonomy constant. Relative-altitude envelope defaults
to 10–500 m AGL (`PX4_MIN_REL_ALT_M`, `PX4_MAX_REL_ALT_M`).

`open-vi --memory` is process-local. For a live bus,
`open-vi --platform px4` connects over STOMP.

An accepted `WAYPOINT_FOLLOWING` is rejected first when the path is
empty, a point is non-finite, or relative altitude is outside the
envelope. Those rejects never start a mission.

## Waypoint execute

An accepted `WAYPOINT_FOLLOWING` uploads a mission, arms, starts MISSION,
and waits until relative altitude shows climb. An Activity UPDATE with
the live `ActivityID` runs the same upload without minting a new
activity. The command is rejected if the link is down, the mode is not
`WAYPOINT_FOLLOWING`, the path fails the envelope check, or Activity
is not UPDATE against the live id.

A-GRA `Point2D` altitude is HAE. PX4 mission items are relative to home.
Home HAE is `GLOBAL_POSITION_INT.alt − relative_alt`. The adapter
subtracts that from each waypoint.

```mermaid
sequenceDiagram
  participant Iso as Isolator
  participant Px4 as Px4MavlinkAdapter
  participant FC as PX4

  Iso->>Px4: submit_flight_command(WAYPOINT_FOLLOWING)
  Px4->>FC: MISSION_COUNT + items
  Note over Px4,FC: item 0 NAV_TAKEOFF, then NAV_WAYPOINT
  Px4->>FC: ARM
  Px4->>FC: set_mode MISSION + MISSION_START
  Px4->>FC: wait relative_alt climb
  Px4-->>Iso: ACCEPTED + activity ACTIVE_UNCONSTRAINED
```

A standalone PX4 TAKEOFF mode sits at `MIS_TAKEOFF_ALT`. Embedding
takeoff as mission item 0 and then `MISSION_START` is the path that
climbs. `apply_system_management` writes `SENS_BARO_QNH` (hPa) and
the local TSPI snapshot (`kollsman_hpa`). Link down or a missing
param ack is `REJECTED`.

## Telemetry

A reader thread ingests HEARTBEAT, GLOBAL_POSITION_INT, ATTITUDE,
VFR_HUD, and SYS_STATUS. `snapshot()` is `AVAILABLE` while heartbeat and
position are fresher than 10 s; otherwise `TEMPORARILY_UNAVAILABLE` /
`PX4_LINK_DOWN`. `get_vehicle_state()` maps lat/lon/alt, NED speeds,
attitude, airspeed, heading, and battery into `TspiSnapshot`.

## Tests

Unit tests mock MAVLink (`tests/test_platform_px4.py`). They are not
live SITL and are not gated on a vehicle.
