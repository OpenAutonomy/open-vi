# Contributing

Pull requests are welcome. Start with [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)
for the layers and [docs/ADDING_A_VEHICLE.md](docs/ADDING_A_VEHICLE.md) if
you are adding a backend.

Found a vulnerability? Do not open a PR for it first —
the security policy at the repo root says how to report it.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
./scripts/lint.sh
pytest
```

That is what CI runs — `./scripts/lint.sh` covers ruff, pylint and
mypy. A new vehicle is a `PlatformPort` implementation.

Wire conformance against A-GRA 5.0a needs the standard, which is not
redistributed here:

```bash
pip install -e ".[validate]"
./scripts/fetch-agra-schema.sh
./scripts/fetch-agra-spec.sh
pytest tests/test_wire_xsd.py tests/test_wire_surface.py
```

The second script fetches the Vehicle Interface Volume, which
`test_wire_surface.py` reads Table 1-38 out of. Message directions in
`docs/FEATURES.md` §1.3.1 come from that table — if a direction looks
wrong, the standard decides, not the implementation.

CI runs that as the `conformance` job. Without the schema those tests
skip, so `pytest` alone stays green. If a change alters published XML,
regenerate the golden corpus with `UPDATE_GOLDEN=1 pytest` and read the
diff before committing it.

Docs (Markdown + Google-style docstrings → MkDocs):

```bash
pip install -e ".[docs]"
mkdocs serve
```

CI runs `mkdocs build --strict`. A public push to `main` publishes
[GitHub Pages](https://openautonomy.github.io/open-vi/) and
`ghcr.io/openautonomy/open-vi`.
