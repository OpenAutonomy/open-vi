# Changelog

## [Unreleased]

### Fixed

- HSA altitude envelope is 0–500 m AGL (home HAE through home+500)
  and is compared on a 0.1 m grid, so a hold at the advertised
  home/current HAE is accepted. Waypoint following stays 10–500 m
  AGL. Home HAE is frozen after the first fix so the offer and the
  accept check do not drift.
- PX4 execution rejects use `STATE_OR_SETTINGS` (a
  `CannotComplyEnum` token). `FAILED` is a processing state and
  was rejected by schema validation on C2.
- HSA offboard primes setpoints, then OFFBOARD, then arm. A
  ground hold near home HAE climbs to takeoff altitude.

### Changed

- Isolator session memory is split: `FlightSession` owns the live
  activity, `RouteExecution` owns live plan execution, and
  `RouteStore.ingested_ids()` lists stored plans for query.
  `IsolatorState` keeps single-owner fields only. Publishers no
  longer write session state.
- UCI message-type names live in `open_vi.codec.mts`. Handlers
  and publishers import those constants instead of each other.
- Platform docs live under `docs/platforms/{stub,px4}/` (README plus
  FEATURES). Isolator Volume coverage stays in
  [docs/FEATURES.md](docs/FEATURES.md).

### Removed

- `Isolator.publish_contingency` and `publishers.publish_contingency`.
  Stub `inject_contingency` stays on tests; Isolator publishes
  faults, subsystem status, or capability from the platform.
- `docs/PX4.md` (moved to `docs/platforms/px4/`).
- `compose/asb.yml`.
- `COMPLIANCE_MODE`. Route, query, and control always publish
  `QUEUED`, `PROCESSING`, then `COMPLETED`.

### Added

- Inbound route DEACTIVATE publishes `MissionPlanActivationStatus`
  (`DEACTIVATED`) for the mission and route plan. Completes
  Volume §1.2.5.4 Receive Deactivate Route.
- Route-sourced `FAILED` / `CANCELED` from the platform aborts the
  live route (DEACTIVATED + FAILED execution +
  `MissionPlanActivationStatus`). Completes Volume §1.2.5.6 VI
  Deactivate Route.
- Query status includes `Result/ID` on `COMPLETED`.
  `QueryIdentifiersOnly` returns those IDs without native bodies.
  A stored-route checksum mismatch is `FAILED` with a reason.
  Completes Volume §1.2.4.1–1.2.4.3.
- PX4 `HSA_CSA`: Isolator parses heading / speed / altitude onto
  `FlightCommandRequest`; `Px4MavlinkAdapter` flies an offboard
  hold (`GROUNDSPEED`, `TRUE_NORTH`, AGL/HAE). Curve following
  stays rejected.
- Live plan-execution status: `ResponsePlanExecutionStatus` carries
  the activated route when one is flying; Isolator also publishes
  `RoutePlanExecutionStatus` and `MA_MissionPlanExecutionStatus`
  (`EXECUTING` on ACTIVATE, `COMPLETED` on route-sourced finish,
  `FAILED` on DEACTIVATE of an executing plan).
- Route ACTIVATE submits stored `MA_RoutePlan` waypoints as
  `WAYPOINT_FOLLOWING` on `PlatformPort` (Capability NEW, or
  Activity UPDATE when an activity is already live). DEACTIVATE
  from ACTIVATED cancels that command. Validation is VALID only
  when the stored path parses to a finite non-empty waypoint list.
- PX4 Flight Autonomy for waypoint following: envelope
  validation with Volume `ValidationResult` reasons,
  `WaypointFollowingPerformanceProfile` min/max altitude on
  `MA_FlightCapability`, and `SENS_BARO_QNH` on
  `MA_SystemManagementRequest`.
- [docs/FEATURES.md](docs/FEATURES.md): ASK 5.0a Vehicle Interface
  Volume coverage, structured as the volume's compliance IDs,
  §1.2 interactions, and §1.3.1 MMS.
- Activity UPDATE on `MA_FlightCommand`: Isolator matches the live
  `ActivityID`, Stub and PX4 replace the path without minting a new
  activity, and `MA_FlightActivity` is published as `UPDATED`.
  Capability NEW while an activity is live is rejected; replan is
  Activity UPDATE only.
- MkDocs on GitHub Pages:
  [openautonomy.github.io/open-vi](https://openautonomy.github.io/open-vi/).
- Container image on GHCR (`ghcr.io/openautonomy/open-vi`), built from
  `Containerfile` on a public push to `main`.

## [0.1.0] - 2026-08-17

First tagged source release. Canonical home is
[OpenAutonomy/open-vi](https://github.com/OpenAutonomy/open-vi).

Isolator owns A-GRA sequences, including the route ladder and File*.
`PlatformPort` is vehicle I/O: snapshot, flight command, TSPI, status /
faults, and QNH. Shared values live in `open_vi.domain`. Stub is the
default backend; PX4 SITL does telemetry and `WAYPOINT_FOLLOWING`.

[0.1.0]: https://github.com/OpenAutonomy/open-vi/releases/tag/v0.1.0
