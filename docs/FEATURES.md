# Features

Coverage of the ASK 5.0a Vehicle Interface Volume (v. 5.0a, 21 APR
2026). Sections follow that volume: §1.2 interactions, then §1.3
compliance and the Minimum Message Set.

This is the Core Mission Use Case unless a row names another MUC.
A single Supported is not a flown product. Each §1.2 row has three
axes. Adapter detail is under [platforms](platforms/README.md).

| Axis | Meaning |
| --- | --- |
| Sequence | Isolator runs the required messages and ladder |
| Execution | Isolator applies the product effect (submit, activate, assign, validate). Store-and-ack or republish-only is not this |
| Backend | A vehicle adapter performs the work Isolator submitted or supplies the facts Isolator publishes |

| Status | Sequence / Execution | Backend |
| --- | --- | --- |
| Supported | The axis is complete for Core | — |
| Partial | Some steps or fields; notes say what is missing | — |
| Not supported | No handler, no effect, or other MUC | — |
| n/a | — | Isolator-only; no vehicle work |
| PX4 | — | `Px4MavlinkAdapter` does the work (SITL) |
| PX4 partial | — | PX4 does part of the work |
| none | — | No adapter implements it |

Stub is the default test backend. It accepts or injects; it does not
fly. Stub rows live in [platforms/stub](platforms/stub/FEATURES.md).
PX4 rows live in [platforms/px4](platforms/px4/FEATURES.md).

§1.2 Core (36 numbered rows): Sequence 29 Supported, 5 Partial, 2 Not
supported (terrain, weapons). Execution 15 Supported, 6 Partial, 13
n/a, 2 Not supported. Backend is not 29/36.

The required fields of *inbound* messages are verified separately, by
`tests/test_wire_inbound_fields.py`: an inbound obligation is met when
the field's content reaches an observable effect, not when a message
carrying it is accepted. The 21 entries are 17 distinct message/field
pairs — ten driven by a test there, seven recorded as not read, each
citing the row it bears on.

The five Partial Sequence rows are §1.2.1.4, §1.2.1.5, §1.2.5.4,
§1.2.5.6 and §1.2.6.6 — each names a field or reply the interaction
requires and open-vi does not yet produce. Two of the five are the one
remaining `MA_Fault` gap, `AmbiguityGroup`, counted once per
interaction that requires it; it is not a missing builder but a
missing capability, since open-vi does no fault isolation.

That reading is now mechanical rather than manual:
`tests/test_wire_required_fields.py` accounts for all 120 required
fields the §1.2 tables name, `GAPS` in that module is the registry
these rows cite, and the set of Partial rows is asserted there in both
directions — so a row cannot drift on or off Supported without the
registry moving with it. `Launch` under §1.2.2 is listed Not supported
without a § and is not in these counts; see that row.

Message directions in §1.3.1 are Table 1-38 of the volume, not
inferred from this implementation. `tests/test_wire_surface.py`
asserts both this file and the code against that table when the
volume is present.

Volume §1.4 (Mission and Flight Autonomy Capabilities) allocates work
to MA or FA. It is not a VI interface checklist, so it is not repeated
here.

## 1.2 Interface interactions

### 1.2.1 Contingencies

| § | Interaction | Seq | Exec | Back | Notes |
| --- | --- | --- | --- | --- | --- |
| 1.2.1.1 | Collision Avoidance | Supported | n/a | none | Republishes the capability pair when `snapshot()` readiness is `CONSTRAINT_COLLISION_AVOIDANCE`. Detect-and-avoid is vehicle-driven; no adapter has it. |
| 1.2.1.2 | Intra-Vehicle Comms Failure | Supported | n/a | n/a | Periodic `SubsystemStatus`; answers `SubsystemStatusDataRequest`. Loss-of-comms plan is MA's. |
| 1.2.1.3 | MA Failsafe | Supported | Partial | PX4 | Ingest `MA_Response` and notify. `ActivatePlan` of a stored route submits `WAYPOINT_FOLLOWING`. No trigger monitor. Missing plan: notify only. |
| 1.2.1.4 | Mechanical Damage Reporting | Partial | n/a | PX4 | Publishes `MA_Fault` from `get_faults()` on the status-package tick and ServiceStatusDataRequest. PX4 BIT is `SYS_STATUS` sensor health. Table 1-4 requires nine fields of `MA_Fault` — exactly the members of A-GRA's `MA_SubsystemFaultType`. Eight are emitted: `Severity`, `DetectionTime`, `FaultCodeCount`, `SubsystemID` and `ServiceID` alongside the original four, with `FaultData` carrying PX4's `SYS_STATUS` health bitfield. `DetectionTime` is stamped when the fault appears and held until it clears, and `FaultCodeCount` counts clear-to-set transitions, because A-GRA says the time is of detection and not of transmission. **Still missing `AmbiguityGroup`:** it means a fault narrowed to a set of candidate components but not yet isolated, and open-vi does no isolation — PX4's health bits name the unhealthy sensor outright. There is no candidate set to report. |
| 1.2.1.5 | Sensor Failure | Partial | n/a | PX4 | Publishes `SubsystemStatus` then `MA_Fault` when the platform reports them. Table 1-5 requires the same nine `MA_Fault` fields as Table 1-4, and `AmbiguityGroup` is likewise the one not emitted; see §1.2.1.4. PX4 severities are this adapter's judgement: `WARNING` for what the airframe cannot fly without, `CAUTION` for degraded but survivable, `ADVISORY` for the RC receiver an autonomous VI is not using. |

### 1.2.2 Control and tasking

| § | Interaction | Seq | Exec | Back | Notes |
| --- | --- | --- | --- | --- | --- |
| 1.2.2.1 | Control by Curve Following | Supported | Supported | PX4 partial | Isolator parses NURBS and submits NEW / UPDATE / CANCEL → status and `MA_FlightActivity`. PX4 samples the spine to a mission. No `CurveTraversingParameters` or `AppendCurve`. |
| 1.2.2.2 | Control by HSA/CSA Command | Supported | Supported | PX4 | Isolator parses and submits NEW / UPDATE / CANCEL. PX4 leftover refs convert onto the offboard hold. `SpeedOptimization` is `REJECTED`. |
| 1.2.2.3 | Control by Waypoint Following | Supported | Supported | PX4 | NEW / UPDATE / CANCEL → status and `MA_FlightActivity`. Optional reject `MA_Task`. Rejects may include `CannotComplyDetails`. No taxi, ATC hold, or payload actions. **Deviation:** in-flight replan uses the `Activity` choice carrying `Ranking` and `FlightControlMode`, which A-GRA's `Activity` does not permit — it allows only `ChangeActivityRank` / `ChangeActivityState` / `DeleteActivity` / `UnassignActivity`. `open-ma` emits the identical shape, so this is a convention shared with the peer, not a one-sided bug; conforming would mean moving replan onto the `Capability` choice in both. |
| 1.2.2.4 | Control Mode Authorization | Supported | n/a | PX4 | Publishes `MA_FlightCapability` then `MA_FlightCapabilityStatus` from `snapshot()`. Performance profile is the adapter. |
| 1.2.2.5 | MA-VI Command Task | Supported | Partial | none | Ingest `MA_Task` and notify. `MA_TaskCommand` NEW / CANCEL → status and `TaskStatus`. No vehicle task. An `MA_Task` the VI cannot store — unparseable, or carrying no `TaskID` — is answered with `MA_SystemNotification` carrying `NotificationDetail`, which §1.2.2.5 requires and which was previously dropped in silence. The acknowledgement of a task the VI did store carries no detail: every `CannotComplyEnum` value states why something failed, so there is no truthful value for a success. |
| 1.2.2.6 | Modify Capabilities | Supported | n/a | PX4 | Republishes when `snapshot()` availability or the advertised offer changes. Mode reduction from another SystemID is §1.2.2.9. |
| 1.2.2.7 | Receive Control Request | Supported | Supported | n/a | ACQUIRE / STEAL / RELEASE with status ladder and `MA_ControlAssignment`. A rejection carries `ApprovalRequestProcessingStateReason`, which Table 1-12 requires, as well as the inherited `RequestProcessingStateReason`. `MA_ControlRequestStatusMDT` extends `RequestStatusBaseType`, so both exist and both are `[0..1]` — neither the XSD nor Table 1-38 can tell which one was filled, so the corpus drives a rejected ACQUIRE to prove it. |
| 1.2.2.8 | Unpair Control Assignment | Supported | Supported | n/a | When availability is not `AVAILABLE`, `CANCELED` status, `REMOVED` assignment, then clear. The `CANCELED` status carries `ApprovalRequestProcessingStateReason`, which Table 1-13 requires; see §1.2.2.7. Table 1-13 also requires four fields of `MA_ControlAssignment` that the A-GRA content model does not give it — they belong to `ControlStatus`, where open-vi emits them; see `FIELDS_NOT_IN_TYPE`. |
| 1.2.2.9 | Update C2 Control Designations | Supported | Supported | n/a | Inbound `MA_FlightCapability` from another SystemID redacts the offer. Isolator readvertises. Commands for a redacted mode are `REJECTED`. |
| — | Launch | Not supported | Not supported | none | A-GRA commands launch through `MA_FlightCommand/Command/Capability/Launch` (`[0..1]`), a choice of `CarrierLaunch` or `AirfieldTakeoff{AirfieldID, RunwayID}` — so the schema prescribes launch *parameters* on a command the VI already handles, even though no §1.2 interaction covers the sequence. The codec does not parse the element and `open-ma` does not send it. `MavlinkLink.arm` / `wait_airborne` are unreferenced primitives kept for it; implementing it would let the VI arm, which is the boundary `REQ-SYS-0004` draws. **§ unconfirmed** — not matched to a numbered §1.2 interaction, so excluded from the row counts |

### 1.2.3 COP

| § | Interaction | Seq | Exec | Back | Notes |
| --- | --- | --- | --- | --- | --- |
| 1.2.3.1 | VI Updates to COP | Supported | n/a | PX4 | Tick republishes the capability pair when `tick_republish_status` is on (default), plus activity, position, weather, navigation, component status, and the status package. Facts are the adapter's. |

### 1.2.4 Data validation

| § | Interaction | Seq | Exec | Back | Notes |
| --- | --- | --- | --- | --- | --- |
| 1.2.4.1 | Checksum Validation | Supported | Supported | n/a | Stored routes emit `FileMetadata` with SHA-256. Query `FAILED` if stored XML no longer matches. |
| 1.2.4.2 | Query for Missing Data | Supported | Partial | n/a | Native MTs by default. `QueryIdentifiersOnly` is IDs only. Empty match is `COMPLETED` with no `Result`. **Table 1-17 requires `Query`, and open-vi does not read it.** `QueryMessageType` carries `MessageType` and `Query`; `parse_query_request` reads only the former, so a query returns every object of the requested types instead of the ones the predicate selects. Table 1-17 is Query for Missing Data, where MA asks for particular ids, so MA must filter what it receives. |
| 1.2.4.3 | Route Plan Data Validation | Supported | Supported | n/a | Composition of the two rows above. |

### 1.2.5 Route plan behaviors

The Isolator `RouteStore` walks PREPARE_FOR_UPLOAD → UPLOAD →
PREPARE_FOR_ACTIVATION → ACTIVATE, or DEACTIVATE. Isolator parses
waypoints from stored `MA_RoutePlan` XML. ACTIVATE submits
`WAYPOINT_FOLLOWING` on `PlatformPort` and commits `ACTIVATED` only
when the platform accepts.

| § | Interaction | Seq | Exec | Back | Notes |
| --- | --- | --- | --- | --- | --- |
| 1.2.5.1 | Activate Route | Supported | Supported | PX4 | Parses the stored path; submits NEW or UPDATE. Publishes `MA_FlightActivity`. No taxi, ATC hold, or payload actions. |
| 1.2.5.2 | Convert and Upload Route | Supported | Partial | none | Stores `MA_RoutePlan`, notifies, and emits File*. No native VMS conversion. |
| 1.2.5.3 | Prepare for Route Activation | Supported | Supported | n/a | Isolator state `READY_FOR_ACTIVATION`. |
| 1.2.5.4 | Receive Deactivate Route | Partial | Supported | PX4 | From ready: store-only. From ACTIVATED: Capability CANCEL and `CANCELED` execution status. Both publish `MissionPlanActivationStatus` `DEACTIVATED`. §1.2.5.4 also requires the `MA_MissionPlanActivationCommandStatus` reply to be `COMPLETED` only when the route was **not** yet EXECUTING, and `FAILED` when it was; open-vi replies `COMPLETED` in both cases. |
| 1.2.5.5 | Validate Route Plan | Supported | Partial | n/a | VALID if stored XML parses to a finite non-empty path and `WeatherAreaData` is not SEVERE/EXTREME icing or turbulence. Envelope rejects stay on ACTIVATE (adapter). |
| 1.2.5.6 | VI Deactivate Route | Partial | Supported | PX4 | Route-sourced stop from the platform: `DEACTIVATED`, `CANCELED` execution status per Table 1-24, clear sessions. Direct flight commands do not abort a route. Table 1-24's other row names `MA_MissionPlanActivationStatusMT` typed as `MA_MissionPlanActivationCommandMT`; the schema defines both `MissionPlanActivationStatus` and `MA_MissionPlanActivationStatus` as distinct messages and Table 1-38 lists only the former, which open-vi publishes. Whether that satisfies the row is unresolved in the volume. |

### 1.2.6 Status

| § | Interaction | Seq | Exec | Back | Notes |
| --- | --- | --- | --- | --- | --- |
| 1.2.6.1 | Exchange Heartbeat — Subsystem Status Reports | Supported | n/a | n/a | Periodic `ServiceStatus` / `SubsystemStatus`; answers both data-request MTs. `MA_Fault` carries `Severity`, which Table 1-25 requires. |
| 1.2.6.2 | Publish Control Status | Supported | n/a | n/a | Isolator is `PrimaryController` and `MissionControl`. Acquired controller is `SecondaryController` when both IDs are stored. `InMission` when a flight, route, or task is live. No `CapabilityManager` or `TransferInfo`. |
| 1.2.6.3 | Query Airfield Update | Supported | Partial | n/a | `AirfieldReport` runway geometry and linked TO/L `MA_RoutePlan`. The field is synthesized from first TSPI (1,500 m, heading 90°), not a surveyed airfield. |
| 1.2.6.4 | Query Route Plan | Supported | Supported | n/a | Preloaded TO/L set plus peer-uploaded plans and File*. |
| 1.2.6.5 | Receive Barometric Pressure | Supported | Supported | PX4 | `MA_SystemManagementRequest` QNH → `apply_system_management`. PX4 writes `SENS_BARO_QNH`. |
| 1.2.6.6 | Receive Execution Status | Partial | n/a | PX4 | Live plan-execution outs on ACTIVATE, tick, COMPLETE, DEACTIVATE-as-CANCELED, and VI abort, each carrying the required `PlanExecutionStatus.PlanExecutionState`. `RoutePlanExecutionStatus` carries `CurrentSegment` from the backend's route progress. Idle activity / route-activity / task plan status is SystemID + Source only. Still Partial: `MA_ActionStatus` is not published. |
| 1.2.6.7 | Receive Vehicle Performance Values | Supported | n/a | PX4 partial | Isolator publishes `snapshot()`. PX4 fills waypoint / HSA / curve altitude min/max. Airspeed, acceleration, and rates come from optional vehicle TOML. |
| 1.2.6.8 | Receive Vehicle State Data | Supported | n/a | PX4 partial | Activity, position, weather, navigation, component status from `get_vehicle_state()`. PX4 omits fuel mass (no sensor). Duration when the port has it. |
| 1.2.6.9 | Request Terrain Data | Not supported | Not supported | none | MUC **MA Terrain Data**. No `ElevationRequest*`. |
| 1.2.6.10 | Vehicle Status Reporting | Supported | n/a | PX4 | Periodic `SubsystemStatus` from the adapter. |
| 1.2.6.11 | VI Responds to Query for Flight Capabilities | Supported | Supported | n/a | Query ladder then native `MA_FlightCapability`. `COMPLETED` includes `Result/ID`. |

### 1.2.7 Weapon employment

| § | Interaction | Seq | Exec | Back | Notes |
| --- | --- | --- | --- | --- | --- |
| 1.2.7.1 | Validate Release Envelope | Not supported | Not supported | none | No strike `TaskID` / release-envelope check. |

## 1.3 Interface compliance

| ID | Requirement | Seq | Exec | Notes |
| --- | --- | --- | --- | --- |
| MA-L1-015 | Support the VI MMS for signals tagged `VI = 1` | Partial | n/a | Core MMS Sequence Supported. `ElevationRequest*` is other MUC. `MA_ActionStatus` is not published. |
| MA-L1-016 | Implement required VI feature-profile sequences (optional sequences excepted) | Supported | Partial | Required Core sequences run. Several rows have no Isolator effect or no adapter. Terrain and weapons are other MUC. |

### 1.3.1 VI MMS

Direction is relative to VI. Core unless noted. This table is
**Sequence** (message present). Execution and Backend stay on the
§1.2 rows.

| Message | Direction | Sequence | Notes |
| --- | --- | --- | --- |
| ActivityPlanExecutionStatus | out | Supported | Idle Source; no ActivityPlanID |
| AirfieldReport | out | Supported | Home field with runway geometry |
| ComponentStatus | out | Supported | |
| ControlStatus | out | Supported | Primary, `MissionControl`, and `SecondaryController` when assigned |
| ElevationRequest | in | Not supported | MUC MA Terrain Data |
| ElevationRequestStatus | out | Not supported | MUC MA Terrain Data |
| FileLocation | out | Supported | Stored routes |
| FileMetadata | out | Supported | SHA-256 of stored XML |
| MA_ActionStatus | out | Not supported | `ActionID` comes from `MA_FlightCommand/Command/Capability/Traceability/Requirement/ActionID` (`[1..1]` within `Requirement`). The codec does not parse `Traceability`, so the id is dropped on ingest. `open-ma` does not populate it either, so the path would never fire today. §1.2.6.6 requires this message, so it is an open Core gap, not a scoping choice |
| MA_ControlAssignment | out | Supported | On control request and VI unpair |
| MA_ControlRequest | in | Supported | ACQUIRE / STEAL / RELEASE |
| MA_ControlRequestStatus | out | Supported | |
| MA_Fault | out | Supported | From `get_faults()` on the status-package tick and ServiceStatusDataRequest |
| MA_FlightActivity | out | Supported | |
| MA_FlightCapability | inout | Supported | Published from the advertised (C2-redacted) offer; inbound designations are consumed |
| MA_FlightCapabilityStatus | out | Supported | |
| MA_FlightCommand | in | Supported | Three Core modes parsed; submit is Execution / Backend |
| MA_FlightCommandStatus | out | Supported | Rejects may include `CannotComplyDetails` |
| MA_MissionPlanActivationCommand | inout | Supported | Inbound ladder; ACTIVATE submits waypoints. Direction per Table 1-38: the outbound leg is §1.2.5.6 VI Deactivate Route. **Not implemented** — on VI abort open-vi emits `MissionPlanActivationStatus` only, so the outbound half of this row is a gap |
| MA_MissionPlanActivationCommandStatus | out | Supported | |
| MA_MissionPlanExecutionStatus | out | Supported | When MissionPlanID is known |
| MA_PositionReportDetailed | out | Supported | |
| MA_Response | in | Supported | Ingest + notify; `ActivatePlan` of a stored route |
| MA_RoutePlan | inout | Supported | Store and query replay |
| MA_SystemManagementRequest | in | Supported | QNH |
| MA_SystemManagementRequestStatus | out | Supported | |
| MA_SystemNotification | out | Supported | Route ingest, failsafe ack, inbound `MA_Task` |
| MA_TaskCommand | in | Supported | |
| MA_TaskCommandStatus | out | Supported | |
| MA_Task | inout | Supported | Ingest + notify; reject suggest outbound |
| MissionPlanActivationStatus | out | Supported | On inbound DEACTIVATE and VI abort (`DEACTIVATED`). |
| NavigationReport | out | Supported | Percent from `get_vehicle_state()`. Duration when the port has it. Fuel mass is the backend; PX4 omits it. |
| QueryDataRequest | in | Supported | Capability, route, airfield |
| QueryDataRequestStatus | out | Supported | Ladder; `Result/ID` on `COMPLETED`; `FAILED` reason on checksum mismatch |
| ResponsePlanExecutionStatus | out | Supported | Idle Source, or live ExecutionState plus plan ids |
| RouteActivityPlanExecutionStatus | out | Supported | Idle Source; no RouteActivityPlanID |
| RoutePlanExecutionStatus | out | Supported | `PlanExecutionStatus` composite; `EXECUTING` / `COMPLETE` / `FAILED` on the wire (the domain says `COMPLETED`). `CurrentSegment` and `NextSegment` from `PlatformPort.active_route_progress()`. `PreviousSegment` is not emitted: its `ActualCaptureTime` is mandatory and the VI does not record capture times |
| RoutePlanValidationCommand | in | Supported | Geometry plus `WeatherAreaData` override |
| RoutePlanValidationCommandStatus | out | Supported | |
| RoutePlanValidation | out | Supported | |
| ServiceStatus | inout | Supported | |
| ServiceStatusDataRequest | in | Supported | |
| ServiceStatusDataRequestStatus | out | Supported | |
| SubsystemStatus | inout | Supported | Published on the status tick and for `SubsystemStatusDataRequest`. Direction per Table 1-38. §1.2.6.1 makes the inbound leg the Flight Autonomy component heartbeat; open-vi takes that over `PlatformPort` (PX4 `SYS_STATUS`), not as inbound UCI, so there is no bus subscription |
| SubsystemStatusDataRequest | in | Supported | |
| SubsystemStatusDataRequestStatus | out | Supported | |
| TaskPlanExecutionStatus | out | Supported | Idle Source; no TaskPlanID |
| TaskStatus | out | Supported | |
| WeatherObservation | out | Supported | |

How Isolator owns sequences is in [ISOLATOR.md](ISOLATOR.md). The
vehicle port is in [PLATFORM.md](PLATFORM.md). Backends are in
[platforms](platforms/README.md).
