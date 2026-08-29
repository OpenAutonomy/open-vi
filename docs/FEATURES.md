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

§1.2 Core (36 rows): Sequence 34 Supported, 2 Not supported
(terrain, weapons). Execution 16 Supported, 5 Partial, 13 n/a, 2
Not supported. Backend is not 34/36.

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
| 1.2.1.4 | Mechanical Damage Reporting | Supported | n/a | PX4 | Publishes `MA_Fault` from `get_faults()` on the status-package tick and ServiceStatusDataRequest. PX4 BIT is `SYS_STATUS` sensor health. |
| 1.2.1.5 | Sensor Failure | Supported | n/a | PX4 | Publishes `SubsystemStatus` then `MA_Fault` when the platform reports them. |

### 1.2.2 Control and tasking

| § | Interaction | Seq | Exec | Back | Notes |
| --- | --- | --- | --- | --- | --- |
| 1.2.2.1 | Control by Curve Following | Supported | Supported | PX4 partial | Isolator parses NURBS and submits NEW / UPDATE / CANCEL → status and `MA_FlightActivity`. PX4 samples the spine to a mission. No `CurveTraversingParameters` or `AppendCurve`. |
| 1.2.2.2 | Control by HSA/CSA Command | Supported | Supported | PX4 | Isolator parses and submits NEW / UPDATE / CANCEL. PX4 leftover refs convert onto the offboard hold. `SpeedOptimization` is `REJECTED`. |
| 1.2.2.3 | Control by Waypoint Following | Supported | Supported | PX4 | NEW / UPDATE / CANCEL → status and `MA_FlightActivity`. Optional reject `MA_Task`. Rejects may include `CannotComplyDetails`. No taxi, ATC hold, or payload actions. |
| 1.2.2.4 | Control Mode Authorization | Supported | n/a | PX4 | Publishes `MA_FlightCapability` then `MA_FlightCapabilityStatus` from `snapshot()`. Performance profile is the adapter. |
| 1.2.2.5 | MA-VI Command Task | Supported | Partial | none | Ingest `MA_Task` and notify. `MA_TaskCommand` NEW / CANCEL → status and `TaskStatus`. No vehicle task. |
| 1.2.2.6 | Modify Capabilities | Supported | n/a | PX4 | Republishes when `snapshot()` availability or the advertised offer changes. Mode reduction from another SystemID is §1.2.2.9. |
| 1.2.2.7 | Receive Control Request | Supported | Supported | n/a | ACQUIRE / STEAL / RELEASE with status ladder and `MA_ControlAssignment`. |
| 1.2.2.8 | Unpair Control Assignment | Supported | Supported | n/a | When availability is not `AVAILABLE`, `CANCELED` status, `REMOVED` assignment, then clear. |
| 1.2.2.9 | Update C2 Control Designations | Supported | Supported | n/a | Inbound `MA_FlightCapability` from another SystemID redacts the offer. Isolator readvertises. Commands for a redacted mode are `REJECTED`. |

### 1.2.3 COP

| § | Interaction | Seq | Exec | Back | Notes |
| --- | --- | --- | --- | --- | --- |
| 1.2.3.1 | VI Updates to COP | Supported | n/a | PX4 | Tick republishes the capability pair when `tick_republish_status` is on (default), plus activity, position, weather, navigation, component status, and the status package. Facts are the adapter's. |

### 1.2.4 Data validation

| § | Interaction | Seq | Exec | Back | Notes |
| --- | --- | --- | --- | --- | --- |
| 1.2.4.1 | Checksum Validation | Supported | Supported | n/a | Stored routes emit `FileMetadata` with SHA-256. Query `FAILED` if stored XML no longer matches. |
| 1.2.4.2 | Query for Missing Data | Supported | Supported | n/a | Native MTs by default. `QueryIdentifiersOnly` is IDs only. Empty match is `COMPLETED` with no `Result`. |
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
| 1.2.5.4 | Receive Deactivate Route | Supported | Supported | PX4 | From ready: store-only. From ACTIVATED: Capability CANCEL and `FAILED` execution status. Both publish `MissionPlanActivationStatus` `DEACTIVATED`. |
| 1.2.5.5 | Validate Route Plan | Supported | Partial | n/a | VALID if stored XML parses to a finite non-empty path and `WeatherAreaData` is not SEVERE/EXTREME icing or turbulence. Envelope rejects stay on ACTIVATE (adapter). |
| 1.2.5.6 | VI Deactivate Route | Supported | Supported | PX4 | Route-sourced `FAILED` / `CANCELED` from the platform: `DEACTIVATED`, `FAILED` execution, clear sessions. Direct flight commands do not abort a route. |

### 1.2.6 Status

| § | Interaction | Seq | Exec | Back | Notes |
| --- | --- | --- | --- | --- | --- |
| 1.2.6.1 | Exchange Heartbeat — Subsystem Status Reports | Supported | n/a | n/a | Periodic `ServiceStatus` / `SubsystemStatus`; answers both data-request MTs. |
| 1.2.6.2 | Publish Control Status | Supported | n/a | n/a | Isolator is `PrimaryController` and `MissionControl`. Acquired controller is `SecondaryController` when both IDs are stored. `InMission` when a flight, route, or task is live. No `CapabilityManager` or `TransferInfo`. |
| 1.2.6.3 | Query Airfield Update | Supported | Partial | n/a | `AirfieldReport` runway geometry and linked TO/L `MA_RoutePlan`. The field is synthesized from first TSPI (1,500 m, heading 90°), not a surveyed airfield. |
| 1.2.6.4 | Query Route Plan | Supported | Supported | n/a | Preloaded TO/L set plus peer-uploaded plans and File*. |
| 1.2.6.5 | Receive Barometric Pressure | Supported | Supported | PX4 | `MA_SystemManagementRequest` QNH → `apply_system_management`. PX4 writes `SENS_BARO_QNH`. |
| 1.2.6.6 | Receive Execution Status | Supported | n/a | PX4 | Live plan-execution outs on ACTIVATE, tick, COMPLETED, DEACTIVATE-as-FAILED, and VI abort. Idle activity / route-activity / task plan status is SystemID + Source only. |
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
| MA_ActionStatus | out | Not supported | Schema requires ActionID Isolator does not have |
| MA_ControlAssignment | out | Supported | On control request and VI unpair |
| MA_ControlRequest | in | Supported | ACQUIRE / STEAL / RELEASE |
| MA_ControlRequestStatus | out | Supported | |
| MA_Fault | out | Supported | From `get_faults()` on the status-package tick and ServiceStatusDataRequest |
| MA_FlightActivity | out | Supported | |
| MA_FlightCapability | inout | Supported | Published from the advertised (C2-redacted) offer; inbound designations are consumed |
| MA_FlightCapabilityStatus | out | Supported | |
| MA_FlightCommand | in | Supported | Three Core modes parsed; submit is Execution / Backend |
| MA_FlightCommandStatus | out | Supported | Rejects may include `CannotComplyDetails` |
| MA_MissionPlanActivationCommand | inout | Supported | Inbound ladder; ACTIVATE submits waypoints |
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
| RoutePlanExecutionStatus | out | Supported | EXECUTING / COMPLETED / FAILED |
| RoutePlanValidationCommand | in | Supported | Geometry plus `WeatherAreaData` override |
| RoutePlanValidationCommandStatus | out | Supported | |
| RoutePlanValidation | out | Supported | |
| ServiceStatus | inout | Supported | |
| ServiceStatusDataRequest | in | Supported | |
| ServiceStatusDataRequestStatus | out | Supported | |
| SubsystemStatus | inout | Supported | Published; inbound ServiceStatus is the peer heartbeat |
| SubsystemStatusDataRequest | in | Supported | |
| SubsystemStatusDataRequestStatus | out | Supported | |
| TaskPlanExecutionStatus | out | Supported | Idle Source; no TaskPlanID |
| TaskStatus | out | Supported | |
| WeatherObservation | out | Supported | |

How Isolator owns sequences is in [ISOLATOR.md](ISOLATOR.md). The
vehicle port is in [PLATFORM.md](PLATFORM.md). Backends are in
[platforms](platforms/README.md).
