# Contributing

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
./scripts/lint.sh
pytest
```

A new vehicle is a `PlatformPort` implementation. See
[docs/ADDING_A_VEHICLE.md](docs/ADDING_A_VEHICLE.md).

Found a vulnerability? [SECURITY.md](SECURITY.md).
