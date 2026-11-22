# Configuration

Every environment variable `open-vi` reads. CLI flags override the
environment; the environment overrides the defaults below.

Two of these change what goes out on the bus rather than how the
process runs — `AGRA_SCHEMA_VERSION` and `AGRA_MESSAGE_MODE` are
written into `MessageHeader` on every outbound message. Setting them
changes what this VI claims to speak.

## Bus (ASB / ActiveMQ STOMP)

Read by `AsbConfig.from_env`.

| Variable | Default | Effect |
| --- | --- | --- |
| `BROKER_HOST` | `localhost` | Broker host for the STOMP session |
| `STOMP_PORT` | `61613` | Broker STOMP port |
| `ASB_USERNAME` | unset | STOMP login. Unset connects anonymously |
| `ASB_PASSWORD` | unset | STOMP passcode. Empty string when a username is set without one |
| `ACTIVEMQ_USER` | unset | Legacy spelling of `ASB_USERNAME`; `ASB_USERNAME` wins |
| `ACTIVEMQ_PASSWORD` | unset | Legacy spelling of `ASB_PASSWORD`; `ASB_PASSWORD` wins |
| `ASB_ANONYMOUS` | unset | `1` / `true` / `yes` discards any credentials and connects anonymously |
| `ASB_HEARTBEAT_MS` | `0` | STOMP heartbeat in both directions. `0` disables |

The broker this is pointed at is normally deployed without
authentication — see [SECURITY.md](https://github.com/OpenAutonomy/open-vi/blob/main/SECURITY.md).
These variables exist so the client can authenticate when the broker
does require it.

## Identity and message header

Read by `IsolatorConfig.from_env`.

| Variable | Default | Effect |
| --- | --- | --- |
| `VI_SYSTEM_NAME` | `open-vi` | Name hashed into the `SystemID` UUID |
| `VI_SYSTEM_LABEL` | `VI_SYSTEM_NAME` | `DescriptiveLabel` beside `SystemID` |
| `VI_NAMESPACE_NAME` | `open-vi` | Namespace name for the `SystemID` UUID5 |
| `VI_NAMESPACE_UUID` | derived | Namespace UUID for the `SystemID` UUID5 |
| `AGRA_SCHEMA_VERSION` | `005.0a` | **On the wire.** `MessageHeader/SchemaVersion`. Defaults to `open_vi.codec.ns.SCHEMA_VERSION` |
| `AGRA_MESSAGE_MODE` | `SIMULATION` | **On the wire.** `MessageHeader/Mode` |

## Isolator timing and outbound

| Variable | Default | Effect |
| --- | --- | --- |
| `VI_TICK_PERIOD_S` | `5` | Seconds between Isolator ticks |
| `VI_TICK_REPUBLISH_STATUS` | `true` | Republish the status package each tick |
| `VI_PUBLISH_STATUS_PACKAGE` | `true` | Publish the status package at startup |
| `VI_PUBLISH_VEHICLE_STATE` | `true` | Publish vehicle-state outs at startup |

Boolean variables accept `1`, `true`, or `yes` (case-insensitive);
anything else is false.

## Backend selection

| Variable | Default | Effect |
| --- | --- | --- |
| `VI_PLATFORM` | `stub` | Backend to construct: `stub` or `px4`. `--platform` overrides |

## PX4 backend

Only read when the PX4 backend is active.

| Variable | Default | Effect |
| --- | --- | --- |
| `PX4_MAVLINK_URL` | `udpin:127.0.0.1:14540` | MAVLink endpoint. `--mavlink-url` overrides |
| `PX4_CONFIG` | unset | Vehicle TOML with the static flight envelope. `--px4-config` overrides |
| `PX4_HEARTBEAT_TIMEOUT_S` | `10` | Seconds to wait for the first HEARTBEAT on connect |
| `PX4_PATH_CLEARANCE_M` | `15.0` | Acceptance radius written to `NAV_ACC_RAD` / `NAV_MC_ALT_RAD` |
| `PX4_MIN_REL_ALT_M` | `10.0` | Floor of the accepted AGL envelope |
| `PX4_MAX_REL_ALT_M` | `500.0` | Ceiling of the accepted AGL envelope |

`PX4_MIN_REL_ALT_M` and `PX4_MAX_REL_ALT_M` are the **lowest**
precedence of three sources. A constructor argument wins first, then
the vehicle TOML, then the environment, then the default — so a TOML
that sets an envelope silently overrides these. The vehicle TOML is in
[platforms/px4](platforms/px4/README.md).
