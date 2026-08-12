# open-vi

A-GRA ASK 5.0a **Vehicle Interface (VI)** — native UCI/A-GRA XML on the Abstract
Service Bus (ASB).

Vehicle backends sit behind a thin `PlatformPort` (`StubPlatform` default;
`Px4MavlinkAdapter` for SITL). Design detail lives under [`docs/`](docs/).

## Install, build and usage

Python 3.11+ required.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"          # includes pymavlink for PX4 tests
# or: pip install -e ".[px4]"    # runtime PX4 only

# Optional local ASB (ActiveMQ STOMP :61613)
docker compose -f compose/asb.yml up -d

open-vi                      # Stub on STOMP
open-vi --platform px4       # PX4 SITL (udpin:127.0.0.1:14540)
open-vi --memory --once      # in-memory advertise once
pytest
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md),
[docs/ASB.md](docs/ASB.md),
[docs/ISOLATOR.md](docs/ISOLATOR.md),
[docs/CODEC.md](docs/CODEC.md),
[docs/PLATFORM.md](docs/PLATFORM.md),
[docs/PX4.md](docs/PX4.md), and
[docs/ADDING_A_VEHICLE.md](docs/ADDING_A_VEHICLE.md).

## Contact

John Henry Burns — [jburns3141@gmail.com](mailto:jburns3141@gmail.com)

## License

see [LICENSE](LICENSE).
