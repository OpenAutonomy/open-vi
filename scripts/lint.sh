#!/usr/bin/env bash
# Lint open-vi against the Google Python Style Guide (pylint), ruff, and
# mypy. Settings for each live in pyproject.toml / .pylintrc.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  PY="$ROOT/.venv/bin/python"
fi

echo "==> ruff check"
"$PY" -m ruff check src tests
echo "==> ruff format --check"
"$PY" -m ruff format --check src tests
echo "==> pylint (Google styleguide .pylintrc)"
"$PY" -m pylint src/open_vi
echo "==> mypy"
"$PY" -m mypy
echo "OK"
