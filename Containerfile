# Runtime image for open-vi. Default is Stub on STOMP.
#
#   docker build -f Containerfile -t open-vi .
#   docker compose -f compose/asb.yml -f compose/vi.yml up --build
#
# BROKER_HOST defaults to the compose service name. Point it at
# host.docker.internal (or the host IP) when the broker is on the host.

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BROKER_HOST=activemq \
    STOMP_PORT=61613 \
    VI_TICK_PERIOD_S=1 \
    AGRA_MESSAGE_MODE=SIMULATION \
    VI_PLATFORM=stub

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir ".[px4]" \
    && useradd --system --uid 10001 --home /app --shell /usr/sbin/nologin vi \
    && chown -R vi:vi /app

USER vi

ENTRYPOINT ["open-vi"]
CMD ["--platform", "stub"]
