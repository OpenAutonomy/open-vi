# Stub

`StubPlatform` is the default `PlatformPort` for tests and `open-vi`.
It is deterministic in-process state: no MAVLink, no motion. Isolator
and the codec never import this module — `make_platform()` and tests
construct it directly.

```mermaid
flowchart LR
  Iso["Isolator"]
  Port["PlatformPort"]
  Stub["StubPlatform"]

  Iso --> Port
  Port --> Stub
```

The port contract is in [PLATFORM.md](../../PLATFORM.md). What Stub
covers versus Isolator is in [FEATURES.md](FEATURES.md).

## Behavior

Default offer is `HSA_CSA`, `WAYPOINT_FOLLOWING`, and
`CURVE_FOLLOWING`, all `AVAILABLE`. `submit_flight_command` accepts
those modes immediately and returns `ACTIVE_UNCONSTRAINED`. It does
not fly a path, track heading, or advance curve progress.

Capability NEW starts an activity when idle. Activity UPDATE replaces
the live path id without minting a new activity. CANCEL clears the
activity when the command id is known. Tests call
`complete_flight_command` when they need a later `COMPLETED`.

`get_vehicle_state()` returns a fixed `TspiSnapshot` (constructor or
default pose). `apply_system_management` stores QNH on that snapshot
as hectopascals. There is no `WaypointFollowingPerformanceProfile`
on the offer.

`inject_contingency` is Stub-only and is not on `PlatformPort`.
`MECHANICAL_DAMAGE` sets a fault. `SENSOR_FAILURE` sets a fault and
`DEGRADED`. `COLLISION_AVOIDANCE` marks the offer `UNAVAILABLE` /
`CONSTRAINT_COLLISION_AVOIDANCE`. `CLEAR` restores operate. Isolator
publishes the matching outs via `publishers.publish_contingency`.

## Run

```bash
open-vi --memory --once
open-vi
```

`--platform stub` is the default. Isolator sequence tests use
`StubPlatform`.
