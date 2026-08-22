# PX4 features

Coverage of what `Px4MavlinkAdapter` does on `PlatformPort`. Isolator
sequences and the VI MMS are in [FEATURES.md](../../FEATURES.md).
Install and SITL are in [README.md](README.md).

| Status | Meaning |
| --- | --- |
| Supported | PX4 SITL runs the port behavior Isolator needs |
| Partial | Some fields or modes exist; execution or curves are missing |
| Not supported | Adapter rejects or has no mapping |

## Control modes

| Mode | Status | Notes |
| --- | --- | --- |
| `WAYPOINT_FOLLOWING` | Supported | Mission upload, arm, takeoff item, MISSION start. Envelope check before upload. Activity UPDATE replans in flight. |
| `HSA_CSA` | Supported | Offboard heading/speed/altitude hold. Leftover refs convert onto NED yaw × groundspeed × AGL: magnetic uses EKF yaw minus compass; TAS / CAS / Mach use wind (or 0) and ISA; MSL / barometric use the home AMSL freeze. Omitted axes hold current. Envelope is 0–500 m AGL (home HAE through home+500), compared on a 0.1 m grid. A ground hold near home climbs to takeoff altitude. Execution rejects use `STATE_OR_SETTINGS`. Magnetic without both headings is `STATE_OR_SETTINGS`. `SpeedOptimization` is `REJECTED`. |
| `CURVE_FOLLOWING` | Supported | Samples the first `CurveSegments` NURBS (or control-point polyline when the knot vector has no degree ≥ 1) to a mission. Same 10–500 m AGL envelope as waypoints. `CurveTraversingParameters` and `AppendCurve` are not implemented. |

Taxi, ATC hold, and payload actions are not implemented. Empty or
non-finite paths, or waypoint relative altitude outside 10–500 m AGL
(defaults), are `REJECTED` with `ValidationResult`
(`INVALID_WAYPOINT` or `PERFORMANCE_LIMIT_EXCEEDED`). HSA uses 0–500 m
AGL so a hold at the advertised home HAE is inside the bound.

## Port methods

| Method | Status | Notes |
| --- | --- | --- |
| `snapshot()` | Supported | `AVAILABLE` while heartbeat and position are fresher than 10 s. Offer includes waypoint / HSA / curve min/max (HAE once home is known, otherwise AGL). Optional vehicle TOML adds airspeed, acceleration, and rate limits as written. |
| `submit_flight_command()` | Supported | `WAYPOINT_FOLLOWING`, `CURVE_FOLLOWING`, and `HSA_CSA`. Link down is `CAPABILITY_UNAVAILABLE`. |
| `poll_command_updates()` | Supported | `COMPLETED` from `MISSION_ITEM_REACHED`. |
| `active_flight_activity()` | Supported | Live mission activity or none. |
| `get_vehicle_state()` | Supported | Lat/lon/alt, NED, attitude, airspeed, heading, battery percent, endurance duration from `BATTERY_STATUS`. Fuel mass is omitted unless the vehicle TOML sets `fuel_mass_kg`. |
| `get_service_status()` | Supported | Process uptime. |
| `get_subsystem_status()` | Supported | `OPERATE` when BIT is clean; `DEGRADED` on link-down or an unhealthy watched sensor. |
| `get_faults()` | Supported | Periodic BIT from `SYS_STATUS` sensor present/enabled/health. Link-down is `PX4_LINK_DOWN`. Healthy is a cleared sentinel. |
| `apply_system_management()` | Supported | Writes `SENS_BARO_QNH` and the local TSPI snapshot. |
| `close()` | Supported | Closes the MAVLink link. |

## Route ACTIVATE

Isolator parses the stored plan and calls
`submit_flight_command`. This adapter flies that path the same as a
direct `MA_FlightCommand`. It does not store or convert
`MA_RoutePlan` XML.

## QNH and envelope

`MA_SystemManagementRequest` QNH is Isolator's. This adapter writes
PX4 `SENS_BARO_QNH`. Envelope limits are this adapter's
(`PX4_MIN_REL_ALT_M` / `PX4_MAX_REL_ALT_M`, or `[envelope]` in the
vehicle TOML), not Isolator's route validation (geometry only).
The optional vehicle TOML (`--px4-config` / `PX4_CONFIG`) is
operator-asserted facts PX4 does not publish. This adapter does
not check those values against the vehicle.
