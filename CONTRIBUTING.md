# Contributing

Pull requests are welcome. Start with [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
for the layers and [docs/ADDING_A_VEHICLE.md](docs/ADDING_A_VEHICLE.md) if
you are adding a backend.

Found a vulnerability? Do not open a PR for it first —
[SECURITY.md](SECURITY.md) says how to report it.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
./scripts/lint.sh
pytest
```

That is what CI runs. A new vehicle is a `PlatformPort` implementation.
