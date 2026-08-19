# Contributing

Pull requests are welcome. Start with [Architecture](ARCHITECTURE.md)
for the layers and [Adding a vehicle](ADDING_A_VEHICLE.md) if you are
adding a backend.

Found a vulnerability? Do not open a PR for it first — see the
[security policy](SECURITY.md).

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
