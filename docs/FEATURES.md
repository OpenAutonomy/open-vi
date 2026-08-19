# Features

Coverage of the ASK 5.0a Vehicle Interface Volume (v. 5.0a, 21 APR
2026). Rows follow that volume: interface compliance IDs, then each
§1.2 interaction, then the §1.3.1 Minimum Message Set.

This is Isolator coverage of the Core Mission Use Case unless a row
names another MUC. `StubPlatform` is the default backend.
`Px4MavlinkAdapter` executes `WAYPOINT_FOLLOWING` only.

| Status | Meaning |
| --- | --- |
| Supported | Required messages and sequence run as Isolator product behavior |
| Partial | Some of the sequence or fields exist; required steps, execution, or fields are missing |
| Not supported | No handler or outbound |

Volume §1.4 (Mission and Flight Autonomy Capabilities) allocates work
to MA or FA. It is not a VI interface checklist, so it is not repeated
here.

## 1.3 Interface compliance

| ID | Requirement | Status |
| --- | --- | --- |
| MA-L1-015 | Support the VI MMS for signals tagged `VI = 1` | Partial |
| MA-L1-016 | Implement required VI feature-profile sequences (optional sequences excepted) | Partial |

## 1.2 Interface interactions

### 1.2.1 Contingencies

| § | Interaction | Status | Notes |
| --- | --- | --- | --- |
| 1.2.1.1 | Collision Avoidance | Partial | Stub can inject `CONSTRAINT_COLLISION_AVOIDANCE` and republish capability status. Not vehicle-driven. |
| 1.2.1.2 | Intra-Vehicle Comms Failure | Supported | Periodic `SubsystemStatus`; answers `SubsystemStatusDataRequest`. Loss-of-comms plan is MA's. |
| 1.2.1.3 | MA Failsafe | Partial | Acks `MA_Response` with `MA_SystemNotification`. Does not store or activate a failsafe route plan. |
| 1.2.1.4 | Mechanical Damage Reporting | Partial | Stub inject publishes `MA_Fault`. No periodic BIT. |
| 1.2.1.5 | Sensor Failure | Partial | Stub inject publishes `SubsystemStatus` then `MA_Fault`. |

### 1.2.2 Control and tasking

| § | Interaction | Status | Notes |
| --- | --- | --- | --- |
| 1.2.2.1 | Control by Curve Following | Partial | Isolator parses and Stub accepts. No Bézier execution or curve progress. PX4 rejects. |
| 1.2.2.2 | Control by HSA/CSA Command | Partial | Isolator parses and Stub accepts. No heading/speed/altitude tracking. PX4 rejects. |
| 1.2.2.3 | Control by Waypoint Following | Supported | Capability NEW / Activity UPDATE / Capability CANCEL → status and `MA_FlightActivity`. Optional reject `MA_Task`. PX4 validates the path and rejects with `CannotComplyDetails/ValidationResult`. Taxi, ATC hold, and payload actions are not implemented. PX4 flies the path. |
| 1.2.2.4 | Control Mode Authorization | Supported | Publishes `MA_FlightCapability` then `MA_FlightCapabilityStatus`. PX4 includes `WaypointFollowingPerformanceProfile` min/max altitude. Stub omits the profile. |
| 1.2.2.5 | MA-VI Command Task | Partial | `MA_TaskCommand` → status and `TaskStatus`. Does not ingest inbound `MA_Task` or notify. |
| 1.2.2.6 | Modify Capabilities | Partial | Availability can change through Stub inject. No FA-driven capability reduction. |
| 1.2.2.7 | Receive Control Request | Partial | ACQUIRE / STEAL / RELEASE with status ladder and `MA_ControlAssignment`. No VI-initiated revoke. |
| 1.2.2.8 | Unpair Control Assignment | Not supported | VI does not publish CANCELED status plus assignment on its own. |
| 1.2.2.9 | Update C2 Control Designations | Not supported | Inbound `MA_FlightCapability` is not consumed to redact modes. |

### 1.2.3 COP

| § | Interaction | Status | Notes |
| --- | --- | --- | --- |
| 1.2.3.1 | VI Updates to COP | Partial | Tick publishes activity, position, weather, navigation, and component status. Capability pair is on advertise, not the COP cadence. |

### 1.2.4 Data validation

| § | Interaction | Status | Notes |
| --- | --- | --- | --- |
| 1.2.4.1 | Checksum Validation | Partial | Stored routes emit `FileMetadata` with SHA-256. Query status has no `Result`; no FAILED reason path. |
| 1.2.4.2 | Query for Missing Data | Partial | Query returns native MTs. No `QueryIdentifiersOnly` ID list. |
| 1.2.4.3 | Route Plan Data Validation | Partial | Composition of the two rows above. |

### 1.2.5 Route plan behaviors

The Isolator `RouteStore` walks PREPARE_FOR_UPLOAD → UPLOAD →
PREPARE_FOR_ACTIVATION → ACTIVATE, or DEACTIVATE. ACTIVATE does not
call the vehicle. Plans are opaque XML plus a hash.

| § | Interaction | Status | Notes |
| --- | --- | --- | --- |
| 1.2.5.1 | Activate Route | Partial | Ladder marks ACTIVATED. No VMS guidance. |
| 1.2.5.2 | Convert and Upload Route | Partial | Stores `MA_RoutePlan`, notifies, and emits File*. No native VMS conversion. |
| 1.2.5.3 | Prepare for Route Activation | Supported | Isolator state `READY_FOR_ACTIVATION`. |
| 1.2.5.4 | Receive Deactivate Route | Partial | DEACTIVATE is accepted from ready or activated. Does not FAILED an executing plan. |
| 1.2.5.5 | Validate Route Plan | Partial | VALID if the plan is stored, else INVALID. `WeatherAreaData` is ignored. |
| 1.2.5.6 | VI Deactivate Route | Not supported | No VI-initiated `MissionPlanActivationStatus` / `RoutePlanExecutionStatus` abort. |

### 1.2.6 Status

| § | Interaction | Status | Notes |
| --- | --- | --- | --- |
| 1.2.6.1 | Exchange Heartbeat — Subsystem Status Reports | Supported | Periodic `ServiceStatus` / `SubsystemStatus`; answers both data-request MTs. |
| 1.2.6.2 | Publish Control Status | Partial | Periodic `ControlStatus` with VI as primary. No `SecondaryController` when MA holds control. |
| 1.2.6.3 | Query Airfield Update | Partial | Stub `AirfieldReport`. No runway geometry or linked TO/L `MA_RoutePlan`. |
| 1.2.6.4 | Query Route Plan | Partial | Returns stored plans plus File*. No preloaded takeoff/landing set. |
| 1.2.6.5 | Receive Barometric Pressure | Supported | `MA_SystemManagementRequest` QNH → COMPLETED or REJECTED. PX4 writes `SENS_BARO_QNH`. |
| 1.2.6.6 | Receive Execution Status | Partial | Idle `ResponsePlanExecutionStatus`; `TaskStatus` on task command. Other plan-execution MTs are not published. |
| 1.2.6.7 | Receive Vehicle Performance Values | Partial | PX4 advertises waypoint min/max altitude. No airspeed or load-factor curves. |
| 1.2.6.8 | Receive Vehicle State Data | Partial | Activity, `MA_PositionReportDetailed`, `WeatherObservation`, `NavigationReport`, `ComponentStatus`. Kinematics are populated; fuel mass/duration are not. |
| 1.2.6.9 | Request Terrain Data | Not supported | MUC **MA Terrain Data**. No `ElevationRequest*`. |
| 1.2.6.10 | Vehicle Status Reporting | Supported | Periodic `SubsystemStatus`. |
| 1.2.6.11 | VI Responds to Query for Flight Capabilities | Supported | Query ladder then native `MA_FlightCapability`. Status has no `Result`. |

### 1.2.7 Weapon employment

| § | Interaction | Status | Notes |
| --- | --- | --- | --- |
| 1.2.7.1 | Validate Release Envelope | Not supported | No strike `TaskID` / release-envelope check. |

## 1.3.1 VI MMS

Direction is relative to VI. Core unless noted.

| Message | Direction | Status | Notes |
| --- | --- | --- | --- |
| ActivityPlanExecutionStatus | out | Not supported | |
| AirfieldReport | out | Partial | Stub home field |
| ComponentStatus | out | Supported | |
| ControlStatus | out | Partial | Primary only |
| ElevationRequest | in | Not supported | MUC MA Terrain Data |
| ElevationRequestStatus | out | Not supported | MUC MA Terrain Data |
| FileLocation | out | Supported | Stored routes |
| FileMetadata | out | Supported | SHA-256 of stored XML |
| MA_ActionStatus | out | Not supported | |
| MA_ControlAssignment | out | Supported | On control request |
| MA_ControlRequest | in | Partial | ACQUIRE / STEAL / RELEASE |
| MA_ControlRequestStatus | out | Supported | |
| MA_Fault | out | Partial | Stub inject; heartbeat may emit |
| MA_FlightActivity | out | Supported | |
| MA_FlightCapability | inout | Partial | Published (PX4 includes waypoint min/max); inbound not consumed |
| MA_FlightCapabilityStatus | out | Supported | |
| MA_FlightCommand | in | Partial | Three Core modes parsed; PX4 flies waypoints |
| MA_FlightCommandStatus | out | Supported | Rejects may include `CannotComplyDetails` |
| MA_MissionPlanActivationCommand | inout | Partial | Inbound ladder only |
| MA_MissionPlanActivationCommandStatus | out | Supported | |
| MA_MissionPlanExecutionStatus | out | Not supported | |
| MA_PositionReportDetailed | out | Supported | |
| MA_Response | in | Partial | Ack only |
| MA_RoutePlan | inout | Supported | Store and query replay |
| MA_SystemManagementRequest | in | Supported | QNH |
| MA_SystemManagementRequestStatus | out | Supported | |
| MA_SystemNotification | out | Supported | Route ingest, failsafe ack |
| MA_TaskCommand | in | Supported | |
| MA_TaskCommandStatus | out | Supported | |
| MA_Task | inout | Partial | Reject suggest only |
| MissionPlanActivationStatus | out | Not supported | |
| NavigationReport | out | Partial | Percent; no fuel mass/duration |
| QueryDataRequest | in | Partial | Capability, route, airfield |
| QueryDataRequestStatus | out | Partial | No `Result` |
| ResponsePlanExecutionStatus | out | Partial | Idle |
| RouteActivityPlanExecutionStatus | out | Not supported | |
| RoutePlanExecutionStatus | out | Not supported | |
| RoutePlanValidationCommand | in | Partial | Presence check |
| RoutePlanValidationCommandStatus | out | Supported | |
| RoutePlanValidation | out | Supported | |
| ServiceStatus | inout | Supported | |
| ServiceStatusDataRequest | in | Supported | |
| ServiceStatusDataRequestStatus | out | Supported | |
| SubsystemStatus | inout | Supported | Published; inbound ServiceStatus is the peer heartbeat |
| SubsystemStatusDataRequest | in | Supported | |
| SubsystemStatusDataRequestStatus | out | Supported | |
| TaskPlanExecutionStatus | out | Not supported | |
| TaskStatus | out | Supported | |
| WeatherObservation | out | Supported | |

How Isolator owns sequences is in [ISOLATOR.md](ISOLATOR.md). The
vehicle port is in [PLATFORM.md](PLATFORM.md).
