# open-vi

open-vi is an ASK 5.0a Level 1 Vehicle Interface. It speaks native UCI/A-GRA
XML on the Abstract Service Bus and drives one vehicle backend through
`PlatformPort`. Isolator owns A-GRA sequences, including the route ladder.
Stub is the default backend; PX4 SITL is telemetry plus
`WAYPOINT_FOLLOWING`.

Owned by [OpenAutonomy](https://github.com/OpenAutonomy). This is an
independent prototype, not an official Open Arsenal product.

## Install and first hour

Python 3.11+.

```bash
git clone https://github.com/OpenAutonomy/open-vi.git
cd open-vi
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
open-vi --memory --once
```

That advertises on an in-process bus and prints a `MA_FlightCapability`
document. There is no broker in this path.

```bash
docker compose -f compose/asb.yml up -d
open-vi                      # Stub on STOMP :61613
# open-vi --platform px4     # PX4 SITL (udpin:127.0.0.1:14540)
pytest
```

PX4 needs `pip install -e ".[px4]"` (already in `.[dev]`) and a SITL on
UDP 14540. See [docs/PX4.md](docs/PX4.md).

The STOMP broker in `compose/asb.yml` has no credentials. Bind it to a
machine you trust. See [SECURITY.md](SECURITY.md).

## Standards

open-vi implements ASK 5.0a message types as CAL-friendly XML. The UCI /
A-GRA XSD catalog is not in this tree and the codec does not validate
against it. Namespace and schema version live in `src/open_vi/codec/ns.py`.

## Layout

| Path | Role |
| --- | --- |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Layers: ASB, domain, codec, Isolator, PlatformPort |
| [`docs/ADDING_A_VEHICLE.md`](docs/ADDING_A_VEHICLE.md) | New vehicle backend |
| [`docs/PLATFORM.md`](docs/PLATFORM.md) | `PlatformPort` methods |
| [`docs/ISOLATOR.md`](docs/ISOLATOR.md) | Sequences and `RouteStore` |
| [`docs/CODEC.md`](docs/CODEC.md) | Parse / build |
| [`docs/ASB.md`](docs/ASB.md) | STOMP and in-memory bus |
| [`docs/PX4.md`](docs/PX4.md) | PX4 SITL backend |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

Released under the MIT License. See [LICENSE](LICENSE).
