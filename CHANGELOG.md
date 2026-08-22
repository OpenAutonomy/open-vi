# Changelog

## [Unreleased]

### Added

- PX4 `NavigationReport` endurance duration from
  `BATTERY_STATUS.time_remaining`, or remaining capacity inferred
  from consumed mAh and current. Fuel mass is omitted unless the
  vehicle TOML sets `fuel_mass_kg`.
- PX4 periodic BIT: `get_faults()` maps `SYS_STATUS` sensor
  health (and link-down) to `MA_Fault`. Isolator emits that on
  the status-package tick.
- Optional PX4 vehicle TOML (`--px4-config` / `PX4_CONFIG`) for
  facts a running instance does not publish: fuel mass, airspeed
  samples, acceleration limits, and climb / turn / descent rates.
  Isolator publishes the port values. The operator owns whether
  they match the vehicle.

### Changed

- PX4 `HSA_CSA` leftover refs convert onto the offboard hold:
  magnetic heading, TAS / CAS / Mach, and MSL / barometric
  altitude. `SpeedOptimization` stays rejected.

## [0.3.0] - 2026-08-22

Isolator-owned Core Volume rows Isolator can fill from existing
state: airfield TO/L, unpair, C2 designations, inbound task,
failsafe, MissionControl, and idle execution-status. PX4 flies
curve following. FEATURES is Isolator coverage: 34/36 §1.2
Supported; leftover rows are other MUC.

### Added

- Query Airfield Update (§1.2.6.3): `AirfieldReport` includes runway
  geometry. Isolator preloads linked takeoff and landing
  `MA_RoutePlan` at construction.
- Query Route Plan (§1.2.6.4): route query returns that preloaded
  TO/L set plus peer-uploaded plans.
- Unpair Control Assignment (§1.2.2.8): when the offer is not
  `AVAILABLE`, Isolator publishes `CANCELED` status and a `REMOVED`
  assignment.
- Update C2 Control Designations (§1.2.2.9): inbound
  `MA_FlightCapability` redacts advertised modes; Isolator
  readvertises the pair.
- MA-VI Command Task (§1.2.2.5): inbound `MA_Task` is ingested and
  acked with `MA_SystemNotification`.
- MA Failsafe (§1.2.1.3): inbound `MA_Response` stores the
  association; `ActivatePlan` flies a stored `MA_RoutePlan`.
- `ControlStatus` includes `MissionControl`: Isolator as
  `ControllerSystemID`, `InMission` when a flight, route, or
  task is live.
- Idle `ActivityPlanExecutionStatus`,
  `RouteActivityPlanExecutionStatus`, and `TaskPlanExecutionStatus`
  (SystemID + Source) on the execution-status package.
- PX4 `CURVE_FOLLOWING`: sample the first NURBS spine (or
  control-point polyline) to a mission using the waypoint
  envelope.

### Changed

- FEATURES §1.2.3.1 is Supported: the default tick republishes
  the capability pair on the COP cadence, not only on advertise.
- FEATURES §1.2.2.1 is Supported: Isolator parses and submits
  curve following; PX4 flies the sampled path.
- FEATURES §1.2.2.2 is Supported: Isolator parses and submits
  HSA/CSA; PX4 tracks the accepted refs.
- FEATURES §1.2.2.6 is Supported: Isolator republishes when
  `snapshot()` or the C2 overlay changes.
- FEATURES §1.2.6.7 is Supported: Isolator publishes the
  platform performance profile; airspeed and load-factor
  curves stay on the backend.
- FEATURES §1.2.1.1 / §1.2.1.4 / §1.2.1.5 are Supported:
  Isolator republishes readiness and publishes
  `SubsystemStatus` / `MA_Fault` from the port. Detect-and-avoid
  and periodic BIT stay on the backend.
- FEATURES §1.2.5.2 is Supported: Isolator stores
  `MA_RoutePlan` and emits File*. Native VMS conversion is
  the backend.
- FEATURES §1.2.6.8 is Supported: Isolator publishes the
  vehicle-state package from `get_vehicle_state()`. Fuel
  mass/duration stay on the backend.
- FEATURES MMS `MA_ControlRequest`, `MA_Fault`,
  `MA_FlightCommand`, `MA_MissionPlanActivationCommand`,
  `NavigationReport`, and `QueryDataRequest` are Supported
  under the same Isolator-coverage rule.
- FEATURES MA-L1-016 is Supported (required Core sequences).
  MA-L1-015 stays Partial (`ElevationRequest*` other MUC;
  `MA_ActionStatus` not published).

## [0.2.0] - 2026-08-21

Isolator-owned Core Volume rows that do not need a new peer or a
new backend: query results, route DEACTIVATE / VI abort, control
`SecondaryController`, and `WeatherAreaData` on validate. CLI and
Isolator injection that was not product behavior is gone.

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

- CLI `--once` (advertise and print capability XML, then exit).
  Isolator still advertises from `start` / `run_forever`.
- `Isolator.add_handler` and the `handlers=` constructor argument.
  Isolator always uses `default_handlers()`.
- Codec `build_sample_hsa_csa_activity_update` (unused test builder).
- `identity.NIL_UUID` and official-harness / SUT identity comments.
- Duplicate `Dockerfile` (image build is `Containerfile`).
- `Isolator.publish_contingency` and `publishers.publish_contingency`.
  Stub `inject_contingency` stays on tests; Isolator publishes
  faults, subsystem status, or capability from the platform.
- `docs/PX4.md` (moved to `docs/platforms/px4/`).
- `compose/asb.yml`.
- `COMPLIANCE_MODE`. Route, query, and control always publish
  `QUEUED`, `PROCESSING`, then `COMPLETED`.
- `isolator.compliance`. `STATUS_LADDER` lives on
  `open_vi.isolator.handlers`.
- Test helper `attach_isolator`; tests call `iso.attach()`.
- `Isolator(..., identity=)`. Identity is always
  `SystemIdentity.named(...)` from config.
- `test_contingency_unknown_kind_raises` (Stub hook validation).

### Added

- Route validate applies `WeatherAreaData` on
  `RoutePlanValidationCommand`. SEVERE / EXTREME icing or
  turbulence is INVALID. Completes Volume §1.2.5.5 Validate
  Route Plan.
- Periodic `ControlStatus` names the acquired controller as
  `SecondaryController` when both SystemID and ServiceID are
  stored. Isolator stays `PrimaryController`. Completes Volume
  §1.2.6.2 Publish Control Status.
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

[0.3.0]: https://github.com/OpenAutonomy/open-vi/releases/tag/v0.3.0
[0.2.0]: https://github.com/OpenAutonomy/open-vi/releases/tag/v0.2.0

## [0.1.0] - 2026-08-17

First tagged source release. Canonical home is
[OpenAutonomy/open-vi](https://github.com/OpenAutonomy/open-vi).

Isolator owns A-GRA sequences, including the route ladder and File*.
`PlatformPort` is vehicle I/O: snapshot, flight command, TSPI, status /
faults, and QNH. Shared values live in `open_vi.domain`. Stub is the
default backend; PX4 SITL does telemetry and `WAYPOINT_FOLLOWING`.

[0.1.0]: https://github.com/OpenAutonomy/open-vi/releases/tag/v0.1.0
