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
| `HSA_CSA` | Partial | Offboard heading/speed/altitude hold. `GROUNDSPEED`, `TRUE_NORTH`, `AGL` / `WGS_HAE` only. Omitted axes hold current. Envelope is 0–500 m AGL (home HAE through home+500), compared on a 0.1 m grid. A ground hold near home climbs to takeoff altitude. Execution rejects use `STATE_OR_SETTINGS`. TAS, CAS, Mach, magnetic heading, MSL, and barometric altitude are `REJECTED`. |
| `CURVE_FOLLOWING` | Not supported | `REJECTED` with `CAPABILITY_NOT_SUPPORTED`. |

Taxi, ATC hold, and payload actions are not implemented. Empty or
non-finite paths, or waypoint relative altitude outside 10–500 m AGL
(defaults), are `REJECTED` with `ValidationResult`
(`INVALID_WAYPOINT` or `PERFORMANCE_LIMIT_EXCEEDED`). HSA uses 0–500 m
AGL so a hold at the advertised home HAE is inside the bound.

## Port methods

| Method | Status | Notes |
| --- | --- | --- |
| `snapshot()` | Supported | `AVAILABLE` while heartbeat and position are fresher than 10 s. Offer includes waypoint and HSA min/max (HAE once home is known, otherwise AGL). |
| `submit_flight_command()` | Partial | `WAYPOINT_FOLLOWING` and `HSA_CSA`. Curve is rejected. Link down is `CAPABILITY_UNAVAILABLE`. |
| `poll_command_updates()` | Supported | `COMPLETED` from `MISSION_ITEM_REACHED`. |
| `active_flight_activity()` | Supported | Live mission activity or none. |
| `get_vehicle_state()` | Partial | Lat/lon/alt, NED, attitude, airspeed, heading, battery. No fuel mass/duration. |
| `get_service_status()` | Supported | Process uptime. |
| `get_subsystem_status()` | Supported | From SYS_STATUS when linked. |
| `get_faults()` | Partial | Link-down and cleared sentinels. No periodic BIT. |
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
(`PX4_MIN_REL_ALT_M` / `PX4_MAX_REL_ALT_M`), not Isolator's route
validation (geometry only).
