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

## Conformance testing

Read by the test suite only; these have no effect on a running VI.

| Variable | Default | Effect |
| --- | --- | --- |
| `UCI_XSD` | unset | Entry document of the UCI / A-GRA XSD catalog. Unset skips `tests/test_wire_xsd.py` entirely |
| `AGRA_SPEC_URL` | upstream `v5.0a` | Source for `scripts/fetch-agra-spec.sh` |
| `AGRA_SPEC_DIR` | `schema/a-gra` | Destination for the fetched Vehicle Interface Volume |
| `AGRA_SCHEMA_URL` | upstream `v5.0a` | Source for `scripts/fetch-agra-schema.sh` |
| `AGRA_SCHEMA_DIR` | `schema/a-gra` | Destination for the fetched XSD catalog |
| `UPDATE_GOLDEN` | unset | Regenerates `tests/golden/` from the current build output instead of asserting against it |

The A-GRA standard is public — Distribution Statement A, approved for
public release — but it is not redistributed in this repository, the
same stance [oa-gateway](https://github.com/OpenAutonomy/oa-gateway)
and `open-ma` take. Fetch it:

```bash
./scripts/fetch-agra-schema.sh
```

Files land in `schema/a-gra/`, which is gitignored, and are checked
against the digests pinned in `scripts/agra-schema.sha256` — the same
source, tag and digests as oa-gateway's `scripts/fetch-agra-schema.sh`.
The two repositories have to agree on what "A-GRA 5.0a" means or their
conformance results are not comparable. Upstream is pinned at the
`v5.0a` tag, not `main`, which has since moved to A-GRA 6.0a.

`tests/test_wire_xsd.py` finds that directory automatically, so
`UCI_XSD` is only needed for a program-specific Message Set or an
offline mirror. One path is enough: the processor resolves
`xs:include` / `xs:import` itself relative to the entry document, so
`A-GRA_MessageDefinitions_v5_0_a.xsd` spans the catalog.

A-GRA 5.0a declares the OAM target namespace this codec emits, so it
is the right entry document for open-vi; the UCI 2.5 catalog
oa-gateway also fetches is a different message set.

The Vehicle Interface Volume is fetched the same way, by
`scripts/fetch-agra-spec.sh`, pinned in `scripts/agra-spec.sha256`.
`tests/test_wire_surface.py` reads **Table 1-38 (VI MMS)** out of it and
asserts both `docs/FEATURES.md` §1.3.1 and the implementation against
it. MA-L1-015 makes that table the compliance requirement, and the
volume states its Direction column is "relative to the VI interface" —
so direction is dictated by the standard, never inferred from this
codebase. Without the volume those tests skip and the
internal-consistency ones still run.

`tests/spec_interactions.py` reads the **per-interaction tables**
(`Table 1-1` through `Table 1-36`) out of the same volume. Each lists,
per message, the fields that interaction requires — the obligation
behind FEATURES' Execution column, which Table 1-38 and the XSD
between them cannot express: Table 1-38 says which messages cross the
interface, the XSD says each is well formed, and neither says a
message carried the substance its use case needed. Almost every A-GRA
element is `[0..1]`, so `MA_FlightCapabilityStatus` without
`AvailabilityReason` satisfies both and tells MA nothing.
`tests/test_spec_interactions.py` pins that parse: the row counts, the
two label/type typos the volume contains, and a bijection onto the 36
interactions FEATURES §1.2 documents.

It is a separate script from the schema fetch on purpose: XSD
validation should not break because a PDF moved.

CI runs this as the `conformance` job. Every published message type
validates, so `KNOWN_NON_CONFORMANT` in that module is empty; it is
kept, and asserted empty in both directions, so a regression has to be
recorded rather than absorbed.

`UPDATE_GOLDEN=1` rewrites the recorded wire corpus. Read the resulting
diff before committing it — that diff is the only review gate on a
change to the wire format.

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
