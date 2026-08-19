# Runtime image for open-vi. Default is Stub on STOMP.
#
#   docker build -f Containerfile -t open-vi .
#   BROKER_HOST=host.docker.internal docker compose -f compose/vi.yml up --build

FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BROKER_HOST=host.docker.internal \
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
