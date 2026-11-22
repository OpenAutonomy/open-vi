"""Runtime configuration: env parsing and the schema-version source."""

from __future__ import annotations

import pytest

from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.config import AsbConfig, IsolatorConfig

_ASB_ENV = (
    "BROKER_HOST",
    "STOMP_PORT",
    "ASB_USERNAME",
    "ASB_PASSWORD",
    "ACTIVEMQ_USER",
    "ACTIVEMQ_PASSWORD",
    "ASB_ANONYMOUS",
    "ASB_HEARTBEAT_MS",
)


@pytest.fixture(autouse=True)
def _clear_asb_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep a developer's shell out of the env-parsing assertions."""
    for name in _ASB_ENV + ("AGRA_SCHEMA_VERSION", "AGRA_MESSAGE_MODE"):
        monkeypatch.delenv(name, raising=False)


# --- schema version: one source of truth ---------------------------------


def test_schema_version_defaults_to_the_codec_constant() -> None:
    """``IsolatorConfig`` must not carry its own copy of the version.

    The wire value is ``MessageHeader/SchemaVersion``, and the codec
    builders default to :data:`open_vi.codec.ns.SCHEMA_VERSION`.
    A second literal here would let the two drift, and
    ``IsolatorContext.schema_version`` prefers the config value, so
    the stale one would win.
    """
    assert IsolatorConfig().schema_version == SCHEMA_VERSION
    assert IsolatorConfig.from_env().schema_version == SCHEMA_VERSION


def test_schema_version_env_override_still_wins(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AGRA_SCHEMA_VERSION", "006.0b")
    assert IsolatorConfig.from_env().schema_version == "006.0b"


def test_message_mode_default_and_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert IsolatorConfig.from_env().message_mode == "SIMULATION"
    monkeypatch.setenv("AGRA_MESSAGE_MODE", "LIVE")
    assert IsolatorConfig.from_env().message_mode == "LIVE"


# --- ASB credentials ------------------------------------------------------


def test_asb_defaults_are_anonymous_localhost() -> None:
    cfg = AsbConfig.from_env()
    assert (cfg.host, cfg.stomp_port) == ("localhost", 61613)
    assert cfg.username is None
    assert cfg.password is None
    assert cfg.heartbeat_ms == 0


def test_asb_credentials_from_asb_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASB_USERNAME", "vi")
    monkeypatch.setenv("ASB_PASSWORD", "secret")
    cfg = AsbConfig.from_env()
    assert (cfg.username, cfg.password) == ("vi", "secret")


def test_asb_credentials_fall_back_to_activemq_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``ACTIVEMQ_*`` is the legacy spelling; ``ASB_*`` takes priority."""
    monkeypatch.setenv("ACTIVEMQ_USER", "legacy")
    monkeypatch.setenv("ACTIVEMQ_PASSWORD", "legacy-pw")
    cfg = AsbConfig.from_env()
    assert (cfg.username, cfg.password) == ("legacy", "legacy-pw")

    monkeypatch.setenv("ASB_USERNAME", "preferred")
    assert AsbConfig.from_env().username == "preferred"


@pytest.mark.parametrize("flag", ["1", "true", "TRUE", "yes"])
def test_asb_anonymous_clears_credentials(
    monkeypatch: pytest.MonkeyPatch, flag: str
) -> None:
    monkeypatch.setenv("ASB_USERNAME", "vi")
    monkeypatch.setenv("ASB_PASSWORD", "secret")
    monkeypatch.setenv("ASB_ANONYMOUS", flag)
    cfg = AsbConfig.from_env()
    assert cfg.username is None
    assert cfg.password is None


def test_asb_anonymous_off_keeps_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASB_USERNAME", "vi")
    monkeypatch.setenv("ASB_ANONYMOUS", "no")
    assert AsbConfig.from_env().username == "vi"


def test_asb_host_port_and_heartbeat_from_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BROKER_HOST", "broker.internal")
    monkeypatch.setenv("STOMP_PORT", "61614")
    monkeypatch.setenv("ASB_HEARTBEAT_MS", "5000")
    cfg = AsbConfig.from_env()
    assert (cfg.host, cfg.stomp_port, cfg.heartbeat_ms) == (
        "broker.internal",
        61614,
        5000,
    )
