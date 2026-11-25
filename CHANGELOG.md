# Changelog

## [Unreleased]

### Security

- Every GitHub Action is pinned to a commit SHA rather than a tag, with
  the release recorded in a trailing comment. A tag is mutable: whoever
  controls the action repository can point `v4` at different code, and
  every workflow trusting that tag runs it. 14 references across 9
  actions.
- The container base image is pinned by digest. `python:3.12-slim-bookworm`
  is rebuilt on every upstream patch, so a tag-only `FROM` means two
  builds of the same commit can differ.

### Added

- `.github/dependabot.yml` for actions, pip and docker. Pinning by SHA
  trades a mutable-tag risk for a staleness risk — nothing moves until
  someone moves it — so dependabot is the other half of that trade: it
  raises the SHA and the version comment together.
  - `upload-pages-artifact` and `deploy-pages` are excluded from the
    grouped actions PR and get their own. Their interaction caused the
    artifact race fixed earlier, so they are worth judging on their own
    CI run.
  - The docker entry is best-effort: dependabot detects `Dockerfile`
    and this repo uses the OCI name `Containerfile`. The config records
    how to bump the digest by hand if no PR appears.

### Changed

- Seven actions bumped to current majors, which clears the Node 20
  deprecation warnings on `checkout`, `setup-python` and
  `upload-artifact`. `upload-pages-artifact` and `deploy-pages` are
  held at their current majors and only SHA-pinned: the pages job is
  failing on a GitHub-side 500 at the time of writing, so a bump there
  could not be distinguished from the ongoing outage.

## [0.6.0] - 2026-11-25

Conformance to A-GRA 5.0a is now measured rather than asserted: every
message the VI publishes is validated against the standard in CI, and
all 36 of them pass. Getting there changed the wire format in seven
ways, so **this release is not compatible with a 0.5.0 peer** — see
Breaking below. Inbound XML is also no longer a resource-exhaustion
vector.

### Breaking

A peer parsing open-vi's output against 0.5.0 shapes will fail. The
wire changes, each made to match the standard:

- `Path` is a linked list of `PathSegment` elements headed by
  `FirstInPathSegmentID`, with positions under
  `EndPoint/WayPoint/PointChoice/Point2D`. It was flat `Segment`
  elements with a `Position` child.
- `MA_RoutePlan` nests geometry under `Plan/Route/Path`, and
  `ForPlanningUseOnly` moves after `Plan`.
- The plan-execution family carries a `PlanExecutionStatus` composite
  instead of flat sibling fields, and emits `Source`.
- `ExecutingSystemID` is now `SystemID` on
  `RoutePlanExecutionStatus` and `MA_MissionPlanExecutionStatus`.
- `PlanExecutionState` uses `COMPLETE`, not `COMPLETED`; a stopped
  route reports `CANCELED`, not `FAILED`.
- `ActivityID` is no longer emitted on the three plan-execution
  messages.
- `MA_Response`'s `DO_NOTHING` option now carries `Trigger` and
  `Response`.

For implementors: `PlatformPort` gains an abstract
`active_route_progress()`. Any out-of-tree backend must implement it;
returning `None` is valid and means "cannot report".

### Security

- Inbound XML is parsed through `defusedxml`, which refuses entity and
  external-reference declarations instead of expanding them. Every
  inbound body reaches the codec through
  `open_vi.codec.xmlutil.parse_xml`, and the bus is unauthenticated,
  so that one function is where the posture is set. Measured against
  the stdlib parser first: a ~310 byte document declaring nested
  entities expanded to ~3 MB with no error, because expat's
  amplification guard does not arm until a document is already large.
  `defusedxml` is a runtime dependency, not an extra.
  `tests/test_codec_xml_hardening.py` holds the boundary and fails
  without the change.

### Added

- Wire conformance harness. One deterministic corpus of every message
  Isolator publishes — captured from the real publish path with the
  in-process bus and Stub backend, covering all 36 publishable message
  types — then four layers over it:
  - `tests/golden/`: byte-exact snapshots, so any change to the wire
    format shows up as a reviewable diff. `UPDATE_GOLDEN=1 pytest`
    regenerates.
  - `test_wire_invariants.py`: envelope child order, `MessageHeader`
    shape, undashed 32-hex UUIDs, UCI timestamp format, and the
    concrete `SchemaVersion`. Nothing previously asserted that value,
    so a wrong one would ship in every message with the suite green.
  - `test_wire_roundtrip.py`: build/parse fidelity for all 14 codec
    pairs that have both sides.
  - `test_wire_surface.py`: FEATURES §1.3.1 and the implementation,
    both against Table 1-38 of the volume.
- XSD validation of that corpus against A-GRA 5.0a, with the
  `validate` extra and `scripts/fetch-agra-schema.sh`. The standard is
  public (Distribution Statement A) but is not redistributed here,
  matching what `oa-gateway` and `open-ma` do: it is fetched into a
  gitignored `schema/a-gra/` and verified against digests pinned in
  `scripts/agra-schema.sha256` — the same source, `v5.0a` tag and
  digests oa-gateway pins, so the two repositories' results are
  comparable. `UCI_XSD` overrides the path, and the tests skip when no
  schema is present.
- `scripts/fetch-agra-spec.sh` fetches the Vehicle Interface Volume,
  pinned in `scripts/agra-spec.sha256`. MA-L1-015 makes Table 1-38 the
  compliance requirement and the volume states its Direction column is
  "relative to the VI interface", so message direction is dictated by
  the standard rather than inferred from this codebase.
- A `conformance` CI job that fetches both standards and runs the XSD
  and Table 1-38 checks on every push and pull request.
- `PlatformPort.active_route_progress()` and
  `open_vi.domain.RouteProgress`, reporting where the vehicle is along
  the waypoint list as submitted. `RoutePlanExecutionStatus` carries
  the `CurrentSegment` the schema requires, plus `NextSegment`.
  - The index is into the *submitted* list, not the uploaded one. PX4
    trims a leading prefix, so its mission sequence `k` is submitted
    index `skipped + k`. Reporting the raw sequence would name the
    wrong waypoint, and a confidently wrong segment is worse than none.
  - `None` means the backend cannot report progress, not index zero.
  - Progress outlives the live activity, because §1.2.5.6 requires a
    `CANCELED` status on VI abort and `CurrentSegment` is mandatory on
    it — an aborted route still has to say where it stopped.
  - `PreviousSegment` is never emitted: its `ActualCaptureTime` is
    mandatory and the VI does not record capture times.
  - `codec.path.segment_id_for_index` is the one home for the
    index-to-id rule, so a status message cannot name a segment the
    route it refers to does not contain.
- `docs/CONFIGURATION.md`: every environment variable open-vi reads,
  with defaults and effect. 14 of the 25 had been undocumented,
  including `AGRA_SCHEMA_VERSION` and `AGRA_MESSAGE_MODE`, which are
  written into `MessageHeader` on every outbound message.

### Changed

- **All 36 published message types validate against A-GRA 5.0a.**
  `KNOWN_NON_CONFORMANT` is empty, and kept rather than deleted
  because it is asserted in both directions — a newly non-conformant
  type fails, and so does a listed type that starts passing.
- `MessageHeader/SchemaVersion` has one source. `config.py` had its
  own literal for both the dataclass default and the
  `AGRA_SCHEMA_VERSION` fallback, and `IsolatorContext` prefers the
  config value, so a future bump of `open_vi.codec.ns.SCHEMA_VERSION`
  would have left messages tagged with the stale copy.
- `SECURITY.md` and `README.md` said the bus has no authentication.
  That is the deployment posture, not a client limitation: open-vi
  sends STOMP credentials when configured. Reworded, and the
  credential variables are documented and covered by tests
  (`config.py` 78% to 100%, `asb/stomp_amq.py` 24% to 65%).
- §1.2 Sequence is 31 Supported / 3 Partial / 2 Not supported, down
  from 34/0/2 at 0.5.0. The count fell because the volume's
  per-interaction tables were read against the code, not because
  anything regressed. §1.2.5.4, §1.2.5.6 and §1.2.6.6 each name a
  field or reply the interaction requires and open-vi does not yet
  produce.
- FEATURES corrections, all claims about the standard that were wrong:
  - `MA_ActionStatus` said the schema requires an `ActionID` the
    Isolator does not have. It arrives at
    `Capability/Traceability/Requirement/ActionID`; the codec drops
    `Traceability` on ingest. `open-ma` does not populate it either,
    so the path would not fire today — but that is a different reason
    from the one recorded.
  - The `Launch` row said the schema prescribes no launch sequence.
    A-GRA prescribes launch *parameters*: `Capability/Launch`, a
    choice of `CarrierLaunch` or
    `AirfieldTakeoff{AirfieldID, RunwayID}`, on a command the VI
    already handles. Neither side implements it.
  - §1.2.5.4 drops to Partial: the
    `MA_MissionPlanActivationCommandStatus` reply must be `COMPLETED`
    only when the route was not yet EXECUTING and `FAILED` when it
    was; open-vi replies `COMPLETED` in both cases.
  - §1.2.5.6 records an unresolved reading rather than a resolution.
    Table 1-24 names `MA_MissionPlanActivationStatusMT` typed as
    `MA_MissionPlanActivationCommandMT`; the schema defines
    `MissionPlanActivationStatus` and `MA_MissionPlanActivationStatus`
    as distinct messages and Table 1-38 lists only the former, which
    open-vi publishes.
- FEATURES §1.2.2.3 records a deviation shared with `open-ma`:
  in-flight replan uses the `Activity` choice carrying `Ranking` and
  `FlightControlMode`, which A-GRA's `Activity` does not permit. Both
  repositories emit the identical shape, so conforming means moving
  replan onto the `Capability` choice on both sides.

### Fixed

- `Path`, `MA_RoutePlan` and `MA_Response` are built as A-GRA defines
  them; see Breaking. The `Path` parser already understood the linked
  form, so it was the builder lagging the reader.
- Plan-execution status carries the `PlanExecutionStatus` composite
  and names the system `SystemID`; §1.2.6.6 names
  `PlanExecutionStatus.PlanExecutionState` as the required field.
- A route reaching completion published `COMPLETED`, which is not a
  `PlanExecutionStateEnum` member. The codec maps domain states to
  wire tokens, leaving the domain vocabulary untouched. An unmapped
  state passes through rather than being rewritten, so a new one fails
  conformance instead of going out as a plausible wrong value, and
  `tests/test_codec_plan_execution.py` drives `RouteExecution`'s own
  setters to assert every reachable state has a token.
- A stopped route reports `CANCELED`. §1.2.5.6 Table 1-24 names it for
  a VI-initiated abort, and an inbound DEACTIVATE is likewise a
  commanded stop. `mark_failed` stays for a genuine execution failure,
  reported on `MA_FlightCommandStatus`.
- FEATURES §1.3.1 directions are Table 1-38's, not this codebase's.
  `SubsystemStatus` and `MA_MissionPlanActivationCommand` are both
  `inout` in the standard; each row now records the implementation gap
  that direction exposes.
- The `pages` job no longer races the artifact API. It uploaded the
  Pages artifact and deployed it back to back in one job, and
  `deploy-pages` queried metadata 1.2s after the upload began — it
  failed three merges, each time leaving the published docs stale,
  including for the 0.5.0 release. The upload now happens in `docs`
  where the HTML is built, so a job boundary separates it from the
  deployment, and both sides use the default artifact name.

## [0.5.0] - 2026-11-22

Isolator serializes session writes, and PX4 command execution moves
off the Isolator thread, so a blocking vehicle command no longer
stalls periodic status and TSPI. VI no longer arms or launches PX4:
readiness requires telemetry showing the vehicle already armed and
airborne, and `LAUNCH` stays an external step. PX4 is a package of
link, mission, offboard, and telemetry. §1.2 rows split into
Sequence, Execution, and Backend — 34/36 is Sequence only.

### Fixed

- PX4 `start_mission` waits for the `DO_SET_MODE` ack before sending
  `MISSION_START`. PX4 denies `MISSION_START` (`COMMAND_ACK`
  result=2) while the `AUTO.MISSION` nav_state transition from the
  preceding mode switch is still in flight; sending the two back to
  back denied the start outright on a fixed-wing airframe. A silent
  mode ack still falls through to `MISSION_START` after a 2 s
  timeout, so an adapter that never acks the switch does not lose
  the start.

### Changed

- Isolator session writes are serialized. After `start`, inbound is
  queued onto the Isolator thread; `dispatch` and the tick take one
  session lock so they cannot interleave.
- `Isolator.start()` now refuses (`RuntimeError`) to run if the
  Isolator thread is already alive, including one `stop()` couldn't
  join within its timeout. `stop()` no longer clears `_thread` when
  the join times out, so a stuck thread stays tracked instead of a
  second thread racing it once the stuck call finally returns.
  `stop()` also takes an optional `timeout` (default `2.0`).
- PX4 `submit_flight_command` validates synchronously and returns
  immediately; arming, mission upload, and waiting for climb now run
  on a background thread, reporting a background failure or a CANCEL
  through `poll_command_updates`. A blocking command no longer stalls
  the Isolator's periodic status/TSPI publishing, which shares one
  thread with inbound dispatch after `start`.
- FEATURES §1.2 rows split into Sequence, Execution, and Backend.
  34/36 is Sequence only. Execution is 16 Supported, 5 Partial.
  Stub is not a flown backend.
- PX4 is a package: link, mission, offboard, and telemetry. The
  adapter composes them. `from open_vi.platform.px4 import
  Px4MavlinkAdapter` is unchanged.
- PX4 vehicle TOML is the static flight envelope only. Remaining
  fuel mass is omitted; it is live state, not a config field.
- PX4 no longer arms or launches the vehicle on Mission Autonomy's
  behalf. Capability readiness (`snapshot()` /
  `MA_FlightCapabilityStatus`) now requires telemetry to show the
  vehicle already armed and airborne (`relative_alt >= 2 m`);
  `TEMPORARILY_UNAVAILABLE` / `PX4_AWAITING_LAUNCH` reports it
  otherwise, alongside the existing `PX4_LINK_DOWN`.
  `submit_flight_command` rejects with the matching reason. A-GRA's
  `LAUNCH` capability is a separate, structurally independent task the
  schema does not prescribe a message sequence for; launching stays an
  external step (QGroundControl, or a boot script driving PX4's own
  `commander` shell) rather than an implicit VI side effect.

### Removed

- The PX4 adapter's implicit arm/takeoff: `mission.py` and
  `offboard.py` no longer arm, upload a `NAV_TAKEOFF` mission item, or
  wait for climb before executing a command. `MavlinkLink.arm` /
  `wait_airborne` remain as unreferenced primitives for a future
  `LAUNCH` capability to reuse.

## [0.4.0] - 2026-08-22

PX4 fills facts Isolator already published: leftover HSA refs,
endurance duration, periodic BIT, and an optional vehicle TOML
for fuel mass and performance extras. Isolator Core stays 34/36
§1.2 Supported; leftover rows are other MUC.

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

[0.4.0]: https://github.com/OpenAutonomy/open-vi/releases/tag/v0.4.0
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
