#!/usr/bin/env bash
# Run official A-GRA VI harness tests against a local Isolator + ASB.
# Prerequisites: docker image compliance-test-harness:1.2.2.a, running ASB
# on localhost:61613, and `open-vi` (Stub) already connected.
# Harness lives in open-ma (gitignored fetch); override with AGRA_HARNESS.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
HARNESS="${AGRA_HARNESS:-${HOME}/open-ma/third_party/a-gra-test-harness}"
TEST="${1:-/app/compliance_test_harness/VI/test_control_by_waypoint_following.py}"
shift || true
CONFIG="${AGRA_HARNESS_CONFIG:-${HARNESS}/configs/test-config.yaml}"

if [[ ! -d "${HARNESS}/compliance_test_harness/VI" ]]; then
  echo "Harness VI tests not found at ${HARNESS}"
  echo "Set AGRA_HARNESS or fetch open-ma third_party/a-gra-test-harness"
  exit 1
fi

docker rm -f open-vi-harness >/dev/null 2>&1 || true
exec docker run --rm --name open-vi-harness \
  --platform linux/amd64 \
  --add-host=host.docker.internal:host-gateway \
  -e BROKER_HOST="${BROKER_HOST:-host.docker.internal}" \
  -e STOMP_PORT="${STOMP_PORT:-61613}" \
  -e TEST_TRIGGERS_ENABLED="${TEST_TRIGGERS_ENABLED:-False}" \
  -v "${HARNESS}/compliance_test_harness:/app/compliance_test_harness" \
  -v "${HARNESS}/common_utils:/app/common_utils" \
  -v "${CONFIG}:/app/test/configs/test-config.yaml" \
  --entrypoint /app/.venv/bin/pytest \
  compliance-test-harness:1.2.2.a \
  -c /app/pyproject.toml \
  --log-cli-level=INFO --tb=short -vv \
  --config=/app/test/configs/test-config.yaml \
  "${TEST}" "$@"
