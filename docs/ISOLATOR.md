# Isolator

The Isolator is open-vi’s A-GRA **VI OMS Isolator** face: UCI XML on the ASB
toward Mission Autonomy, and `PlatformPort` toward the vehicle. It is the only
component that owns A-GRA sequences, including the route ladder and File*.

Parent: [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Runtime

```mermaid
sequenceDiagram
  participant Bus as AsbPort
  participant Iso as Isolator
  participant H as Handlers
  participant R as RouteStore
  participant P as PlatformPort

  Iso->>Bus: connect + subscribe handler inbound_mts
  Iso->>P: snapshot()
  Iso->>Bus: publish MA_FlightCapability
  Iso->>Bus: publish MA_FlightCapabilityStatus ready

  loop tick
    Iso->>P: poll readiness / state as needed
    Iso->>Bus: periodic status / TSPI / status package
  end

  Bus-->>Iso: inbound MT xml
  Iso->>H: dispatch
  H->>P: snapshot / flight command / TSPI / QNH
  H->>R: ingest / activate / File*
  H->>Bus: publish replies
```

`Isolator.__init__` requires `platform: PlatformPort`. The CLI passes one via
`make_platform()`. There is no default Stub and Isolator does not import Stub.

`Isolator.attach()` connects the bus, registers `dispatch`, and subscribes each
handler’s `inbound_mts`. `start()` attaches, advertises control, and runs the
tick loop. Handlers parse with `codec/`, call `RouteStore` and/or
`PlatformPort`, and publish replies. Missing request/response IDs are dropped.

---

## Package

```text
src/open_vi/isolator/
  executive.py      # Isolator lifecycle + dispatch
  publishers.py     # advertise, TSPI, status package, contingency outs
  compliance.py     # loose vs strict status ladders
  context.py        # bus, platform, identity, config, state, routes
  state.py          # capability / activity session
  routes.py         # RouteStore — A-GRA ladder + stored plan bytes
  handlers/
    flight_command.py
    heartbeat.py
    route.py
    failsafe.py
    system_mgmt.py
    query.py
    control.py
    task.py
```

Related: `asb/`, `codec/`, `domain/`, `platform/`, `identity.py`, `config.py`.

---

## RouteStore

`routes.py` sits next to `state.py`. It is the only owner of A-GRA route
sequences:

- ingest / retain opaque `MA_RoutePlan` bytes + sha256
- upload → prepare → activate → deactivate
- `prime(...)` for tests

`IsolatorState.stored_route_ids` lists plans the query handler may emit.
Handlers `route.py` and `query.py` read and write `ctx.routes`, not
`ctx.platform`. ACTIVATE does not call the vehicle.

---

## Handlers

Each handler declares `inbound_mts` (subscribed at `attach`) and maps one
concern: parse → `RouteStore` and/or `PlatformPort` → publish.

| Handler | Inbound | Outbound |
| --- | --- | --- |
| `flight_command` | `MA_FlightCommand` | `MA_FlightCommandStatus` (+ `MA_FlightActivity` if accepted; `MA_Task` Flight suggest if rejected) |
| `heartbeat` | `ServiceStatus`, `ServiceStatusDataRequest`, `SubsystemStatusDataRequest` | Matching status / request-status (fault / capability status as needed) |
| `route` | `MA_MissionPlanActivationCommand`, `MA_RoutePlan`, `RoutePlanValidationCommand` | Activation status ladder (`BySubPlan`/`RoutePlan` or `ByMissionPlan`); notification + `FileLocation` + `FileMetadata`; `RoutePlanValidation` + status |
| `failsafe` | `MA_Response` | `MA_SystemNotification` |
| `system_mgmt` | `MA_SystemManagementRequest` | `MA_SystemManagementRequestStatus` |
| `query` | `QueryDataRequest` | `QueryDataRequestStatus` + native outs (`MA_FlightCapability`, File*/`MA_RoutePlan`, `AirfieldReport`) |
| `control` | `MA_ControlRequest` | `MA_ControlRequestStatus` + `MA_ControlAssignment` (NEW / REMOVED) |
| `task` | `MA_TaskCommand` | `MA_TaskCommandStatus` + `TaskStatus` |

`COMPLIANCE_MODE=loose|strict` selects OPT status ladders on route and query.
Advertise, TSPI, status package, and Stub contingencies are outbound-only
(`publishers.py`), not handlers.

The Isolator does not import STOMP, ActiveMQ, MAVLink, or PX4. Vehicle
backends implement `PlatformPort` (see [PLATFORM.md](PLATFORM.md),
[PX4.md](PX4.md)). Stub-only contingency injection stays off that ABC.
