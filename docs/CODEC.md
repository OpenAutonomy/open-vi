# Codec

The codec package parses and builds UCI/A-GRA XML for Isolator handlers and
publishers. It turns message-type XML into small Python structs (and the
reverse). It is not a full XSD binding and does not perform schema validation
today.

Parent: [ARCHITECTURE.md](ARCHITECTURE.md).

---

## Role

```mermaid
flowchart LR
  H["Handlers / publishers"]
  C["codec/"]
  XML["UCI XML bytes"]

  H <-->|"parse / build"| C
  C <--> XML
```

Handlers and publishers import builders/parsers from submodules, for example:

```python
from open_vi.codec.capability import build_flight_capability
from open_vi.codec.command import parse_flight_commands
```

---

## Conventions

| Rule | Detail |
| --- | --- |
| Namespace | Default `xmlns` = OAM URI in `ns.py` (CAL-friendly; no `uci:` prefix) |
| Schema version | `005.0a` (`SCHEMA_VERSION`) |
| Envelopes | Shared helpers in `xmlutil` (`message_envelope`, IDs, security) |
| Structs | Platform DTOs and small request/result types — not generated XSD classes |

---

## Modules

| Module | Message types (representative) |
| --- | --- |
| `capability.py` | `MA_FlightCapability`, `MA_FlightCapabilityStatus` |
| `command.py` | `MA_FlightCommand`, status, activity |
| `vehicle_state.py` | TSPI outs (`MA_PositionReportDetailed`, `NavigationReport`, …) |
| `status.py` | `ServiceStatus`, `SubsystemStatus`, `MA_Fault` |
| `route.py` | Route plan / activation command + status, File* |
| `notification.py` | `MA_SystemNotification`, `MA_Response` parse |
| `query.py` | `QueryDataRequest` / status / `AirfieldReport` |
| `system_mgmt.py` | `MA_SystemManagementRequest` / status |
| `control.py` | `MA_ControlRequest` / status / `MA_ControlAssignment` |
| `task.py` | `MA_TaskCommand` / status / `TaskStatus` / `MA_Task` |
| `control_status.py` | `ControlStatus`, `ResponsePlanExecutionStatus` |
| `xmlutil.py` / `ns.py` | Shared XML helpers and constants |

---

## Package

```text
src/open_vi/codec/
  ns.py
  xmlutil.py
  capability.py
  command.py
  vehicle_state.py
  status.py
  route.py
  notification.py
  query.py
  system_mgmt.py
  control.py
  task.py
  control_status.py
```
