# Stub features

Coverage of what `StubPlatform` does on `PlatformPort`. Isolator
sequences and the VI MMS are in [FEATURES.md](../../FEATURES.md).
The adapter description is in [README.md](README.md).

| Status | Meaning |
| --- | --- |
| Supported | Stub implements the port behavior Isolator needs |
| Partial | Accept or inject exists; vehicle execution or fields are missing |
| Not supported | Stub rejects or has no hook |

## Control modes

| Mode | Status | Notes |
| --- | --- | --- |
| `WAYPOINT_FOLLOWING` | Partial | Accepts NEW / UPDATE / CANCEL. No path tracking. Waypoints are not required. |
| `HSA_CSA` | Partial | Accepts. No heading/speed/altitude tracking. |
| `CURVE_FOLLOWING` | Partial | Accepts. No Bézier execution or curve progress. |

Capability NEW while an activity is live is rejected. Replan is
Activity UPDATE only. Unknown modes are `REJECTED`.

## Port methods

| Method | Status | Notes |
| --- | --- | --- |
| `snapshot()` | Partial | Offer lists all three modes, all `AVAILABLE`. No waypoint min/max profile. |
| `submit_flight_command()` | Partial | Immediate accept/reject. No vehicle upload. |
| `poll_command_updates()` | Supported | Drains `complete_flight_command` terminals. |
| `active_flight_activity()` | Supported | Live `ACTIVE_UNCONSTRAINED` or none. |
| `get_vehicle_state()` | Partial | Fixed TSPI. Fuel percent is a constant; no fuel mass/duration. |
| `get_service_status()` | Supported | Process uptime. |
| `get_subsystem_status()` | Supported | `OPERATE`, or `DEGRADED` after `SENSOR_FAILURE`. |
| `get_faults()` | Partial | Cleared sentinel, or a SET fault after inject. No periodic BIT. |
| `apply_system_management()` | Supported | QNH stored on the TSPI snapshot (kPa → hPa). Always `COMPLETED`. |
| `close()` | Supported | No-op. |

## Harness hooks (not on the ABC)

| Hook | Status | Notes |
| --- | --- | --- |
| `inject_contingency` | Partial | Collision avoidance, mechanical damage, sensor failure, clear. Not vehicle-driven. |
| `set_readiness` | Supported | Test helper. |
| `complete_flight_command` | Supported | Queues `COMPLETED` for Isolator tick. |

## Route ACTIVATE

Isolator parses the plan and calls `submit_flight_command`. Stub
accepts `WAYPOINT_FOLLOWING` the same as a direct command. There is
no VMS conversion or envelope check.
