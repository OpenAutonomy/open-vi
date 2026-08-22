# Features

Coverage of the ASK 5.0a Vehicle Interface Volume (v. 5.0a, 21 APR
2026). Sections follow that volume: §1.2 interactions, then §1.3
compliance and the Minimum Message Set.

This is Isolator coverage of the Core Mission Use Case unless a row
names another MUC. Backend coverage is under
[platforms](platforms/README.md).

| Status | Meaning |
| --- | --- |
| Supported | Required messages and sequence run as Isolator product behavior |
| Partial | Some of the sequence or fields exist; required steps, execution, or fields are missing |
| Not supported | No handler or outbound |

Volume §1.4 (Mission and Flight Autonomy Capabilities) allocates work
to MA or FA. It is not a VI interface checklist, so it is not repeated
here.

## 1.2 Interface interactions

### 1.2.1 Contingencies

| § | Interaction | Status | Notes |
| --- | --- | --- | --- |
| 1.2.1.1 | Collision Avoidance | Supported | Republishes the capability pair when `snapshot()` readiness is `CONSTRAINT_COLLISION_AVOIDANCE`. Vehicle-driven detect-and-avoid is the backend. |
| 1.2.1.2 | Intra-Vehicle Comms Failure | Supported | Periodic `SubsystemStatus`; answers `SubsystemStatusDataRequest`. Loss-of-comms plan is MA's. |
| 1.2.1.3 | MA Failsafe | Supported | Inbound `MA_Response` is stored and acked with `MA_SystemNotification`. `ActivatePlan` that names a stored `MA_RoutePlan` submits `WAYPOINT_FOLLOWING` and publishes execution status. Trigger monitoring is not implemented. If the plan is not stored, Isolator notifies only. |
| 1.2.1.4 | Mechanical Damage Reporting | Supported | Publishes `MA_Fault` from `get_faults()` on the status-package tick and on ServiceStatusDataRequest. PX4 BIT is `SYS_STATUS` sensor health. |
| 1.2.1.5 | Sensor Failure | Supported | Publishes `SubsystemStatus` then `MA_Fault` when the platform reports them. |

### 1.2.2 Control and tasking

| § | Interaction | Status | Notes |
| --- | --- | --- | --- |
| 1.2.2.1 | Control by Curve Following | Supported | Isolator parses the NURBS and submits Capability NEW / Activity UPDATE / Capability CANCEL → status and `MA_FlightActivity`. PX4 samples the spine to a mission. Stub accepts only. `CurveTraversingParameters` and `AppendCurve` are not implemented. |
| 1.2.2.2 | Control by HSA/CSA Command | Supported | Isolator parses and submits Capability NEW / Activity UPDATE / Capability CANCEL → status and `MA_FlightActivity`. PX4 converts leftover refs onto the offboard hold. `SpeedOptimization` is `REJECTED`. Stub accepts only. |
| 1.2.2.3 | Control by Waypoint Following | Supported | Capability NEW / Activity UPDATE / Capability CANCEL → status and `MA_FlightActivity`. Optional reject `MA_Task`. Rejects may include `CannotComplyDetails/ValidationResult` from the platform. Taxi, ATC hold, and payload actions are not implemented. |
| 1.2.2.4 | Control Mode Authorization | Supported | Publishes `MA_FlightCapability` then `MA_FlightCapabilityStatus` from `snapshot()`. Performance profile is the backend. |
| 1.2.2.5 | MA-VI Command Task | Supported | Inbound `MA_Task` is stored and acked with `MA_SystemNotification`. Own reject-suggest publishes are ignored. `MA_TaskCommand` NEW / CANCEL → status and `TaskStatus`. |
| 1.2.2.6 | Modify Capabilities | Supported | Isolator republishes the capability pair when `snapshot()` availability or the advertised offer changes. Mode reduction from another SystemID is §1.2.2.9. There is no separate FA command. |
| 1.2.2.7 | Receive Control Request | Supported | ACQUIRE / STEAL / RELEASE with status ladder and `MA_ControlAssignment`. VI-initiated revoke is §1.2.2.8. |
| 1.2.2.8 | Unpair Control Assignment | Supported | When availability is not `AVAILABLE`, Isolator publishes `CANCELED` `MA_ControlRequestStatus` for the stored acquire/steal RequestID and `MA_ControlAssignment` as `REMOVED`, then clears the assignment. |
| 1.2.2.9 | Update C2 Control Designations | Supported | Inbound `MA_FlightCapability` from another SystemID intersects the platform offer. Isolator readvertises the redacted pair. Own publishes are ignored. `ObjectState` `REMOVED` clears the overlay. Commands for a redacted mode are `REJECTED`. |

### 1.2.3 COP

| § | Interaction | Status | Notes |
| --- | --- | --- | --- |
| 1.2.3.1 | VI Updates to COP | Supported | Tick republishes the capability pair when `tick_republish_status` is on (default), plus activity, position, weather, navigation, component status, and the status package. |

### 1.2.4 Data validation

| § | Interaction | Status | Notes |
| --- | --- | --- | --- |
| 1.2.4.1 | Checksum Validation | Supported | Stored routes emit `FileMetadata` with SHA-256. Query `FAILED` with `RequestProcessingStateReason` if stored XML no longer matches that digest. |
| 1.2.4.2 | Query for Missing Data | Supported | Native MTs by default. `QueryIdentifiersOnly` returns `Result/ID` and no bodies. An empty match is `COMPLETED` with no `Result`. |
| 1.2.4.3 | Route Plan Data Validation | Supported | Composition of the two rows above. |

### 1.2.5 Route plan behaviors

The Isolator `RouteStore` walks PREPARE_FOR_UPLOAD → UPLOAD →
PREPARE_FOR_ACTIVATION → ACTIVATE, or DEACTIVATE. Isolator parses
waypoints from stored `MA_RoutePlan` XML. ACTIVATE submits
`WAYPOINT_FOLLOWING` on `PlatformPort` and commits `ACTIVATED` only
when the platform accepts.

| § | Interaction | Status | Notes |
| --- | --- | --- | --- |
| 1.2.5.1 | Activate Route | Supported | Parses the stored path; submits Capability NEW or Activity UPDATE. Publishes `MA_FlightActivity`. Taxi, ATC hold, and payload actions are not implemented. |
| 1.2.5.2 | Convert and Upload Route | Supported | Stores `MA_RoutePlan`, notifies, and emits File*. Native VMS conversion is the backend. |
| 1.2.5.3 | Prepare for Route Activation | Supported | Isolator state `READY_FOR_ACTIVATION`. |
| 1.2.5.4 | Receive Deactivate Route | Supported | DEACTIVATE from ready is store-only. From ACTIVATED, Capability CANCEL clears the live activity and publishes `FAILED` execution status. Both publish `MissionPlanActivationStatus` as `DEACTIVATED`. |
| 1.2.5.5 | Validate Route Plan | Supported | VALID if stored XML parses to a finite non-empty path and `WeatherAreaData` (when present) is not SEVERE/EXTREME icing or turbulence. Envelope rejects stay on ACTIVATE (backend). |
| 1.2.5.6 | VI Deactivate Route | Supported | When a route-sourced command returns `FAILED` or `CANCELED`, Isolator commits `DEACTIVATED`, publishes `FAILED` execution status and `MissionPlanActivationStatus`, and clears the live sessions. No inbound command status. Direct flight commands do not abort a route. |

### 1.2.6 Status

| § | Interaction | Status | Notes |
| --- | --- | --- | --- |
| 1.2.6.1 | Exchange Heartbeat — Subsystem Status Reports | Supported | Periodic `ServiceStatus` / `SubsystemStatus`; answers both data-request MTs. |
| 1.2.6.2 | Publish Control Status | Supported | Periodic `ControlStatus` with VI as `PrimaryController` and `MissionControl` (`ControllerSystemID` is Isolator; `InMission` when a flight, route, or task is live). The acquired controller is `SecondaryController` when both SystemID and ServiceID are stored. No `CapabilityManager` or `TransferInfo`. |
| 1.2.6.3 | Query Airfield Update | Supported | `AirfieldReport` includes `Information/Runway` (direction, length, takeoff/landing Start+Limit). Query also emits the linked takeoff and landing `MA_RoutePlan`. |
| 1.2.6.4 | Query Route Plan | Supported | Returns the preloaded TO/L set plus peer-uploaded plans and File*. |
| 1.2.6.5 | Receive Barometric Pressure | Supported | `MA_SystemManagementRequest` QNH → `apply_system_management` → COMPLETED or REJECTED. |
| 1.2.6.6 | Receive Execution Status | Supported | Live `ResponsePlanExecutionStatus` / `RoutePlanExecutionStatus` / `MA_MissionPlanExecutionStatus` on ACTIVATE, tick, COMPLETED, inbound DEACTIVATE-as-FAILED, and VI abort. Idle `ActivityPlanExecutionStatus`, `RouteActivityPlanExecutionStatus`, and `TaskPlanExecutionStatus` are SystemID + Source (no ActivityPlan / RouteActivityPlan / TaskPlan IDs). `TaskStatus` on task command. |
| 1.2.6.7 | Receive Vehicle Performance Values | Supported | Isolator publishes `FlightCapabilityPerformanceProfile` from `snapshot()`. PX4 fills waypoint / HSA / curve altitude min/max. Airspeed, acceleration, and rate limits come from the optional PX4 vehicle TOML; Isolator does not invent them. |
| 1.2.6.8 | Receive Vehicle State Data | Supported | Activity, `MA_PositionReportDetailed`, `WeatherObservation`, `NavigationReport`, `ComponentStatus` from `get_vehicle_state()`. Duration is emitted when the port has it. Fuel mass is the backend; Isolator does not invent it. PX4 omits mass (no sensor). |
| 1.2.6.9 | Request Terrain Data | Not supported | MUC **MA Terrain Data**. No `ElevationRequest*`. |
| 1.2.6.10 | Vehicle Status Reporting | Supported | Periodic `SubsystemStatus`. |
| 1.2.6.11 | VI Responds to Query for Flight Capabilities | Supported | Query ladder then native `MA_FlightCapability`. `COMPLETED` includes `Result/ID` for the capability. |

### 1.2.7 Weapon employment

| § | Interaction | Status | Notes |
| --- | --- | --- | --- |
| 1.2.7.1 | Validate Release Envelope | Not supported | No strike `TaskID` / release-envelope check. |

## 1.3 Interface compliance

| ID | Requirement | Status | Notes |
| --- | --- | --- | --- |
| MA-L1-015 | Support the VI MMS for signals tagged `VI = 1` | Partial | Core MMS Supported. `ElevationRequest*` is other MUC. `MA_ActionStatus` is not published. |
| MA-L1-016 | Implement required VI feature-profile sequences (optional sequences excepted) | Supported | Required Core sequences. Terrain and weapons are other MUC. |

### 1.3.1 VI MMS

Direction is relative to VI. Core unless noted.

| Message | Direction | Status | Notes |
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
| MA_FlightCommand | in | Supported | Three Core modes parsed; submit is the backend |
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
