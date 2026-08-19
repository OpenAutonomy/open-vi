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

That is what CI runs. A new vehicle is a `PlatformPort` implementation.

Docs (Markdown + Google-style docstrings → MkDocs):

```bash
pip install -e ".[docs]"
mkdocs serve
```

CI runs `mkdocs build --strict`. A public push to `main` publishes
[GitHub Pages](https://openautonomy.github.io/open-vi/).
