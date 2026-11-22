"""StompActiveMqAdapter session setup (faked broker; no live STOMP)."""

from __future__ import annotations

from typing import Any

import pytest
import stomp

from open_vi.asb.stomp_amq import StompActiveMqAdapter
from open_vi.config import AsbConfig


class _FakeConn:
    """Records what the adapter asked stomp.py to do."""

    def __init__(self, **kwargs: Any) -> None:
        self.init_kwargs = kwargs
        self.connect_kwargs: dict[str, Any] | None = None
        self.listeners: dict[str, Any] = {}
        self.subscriptions: list[dict[str, Any]] = []
        self.sent: list[dict[str, Any]] = []
        self.disconnected = False
        self._connected = False

    def set_listener(self, name: str, listener: Any) -> None:
        self.listeners[name] = listener

    def connect(self, **kwargs: Any) -> None:
        self.connect_kwargs = kwargs
        self._connected = True

    def is_connected(self) -> bool:
        return self._connected

    def subscribe(self, **kwargs: Any) -> None:
        self.subscriptions.append(kwargs)

    def send(self, **kwargs: Any) -> None:
        self.sent.append(kwargs)

    def disconnect(self) -> None:
        self.disconnected = True
        self._connected = False


@pytest.fixture
def fake_conns(monkeypatch: pytest.MonkeyPatch) -> list[_FakeConn]:
    """Replace stomp.Connection; return the list of built fakes."""
    built: list[_FakeConn] = []

    def factory(**kwargs: Any) -> _FakeConn:
        conn = _FakeConn(**kwargs)
        built.append(conn)
        return conn

    monkeypatch.setattr(stomp, "Connection", factory)
    return built


# --- credentials ----------------------------------------------------------


def test_connect_sends_credentials_when_configured(
    fake_conns: list[_FakeConn],
) -> None:
    """A credentialed broker gets username/passcode on CONNECT."""
    adapter = StompActiveMqAdapter(AsbConfig(username="vi", password="secret"))
    adapter.connect()
    assert fake_conns[0].connect_kwargs == {
        "wait": True,
        "username": "vi",
        "passcode": "secret",
    }


def test_connect_is_anonymous_without_a_username(
    fake_conns: list[_FakeConn],
) -> None:
    """No username means no credential headers at all, not empty ones."""
    adapter = StompActiveMqAdapter(AsbConfig())
    adapter.connect()
    assert fake_conns[0].connect_kwargs == {"wait": True}


def test_connect_sends_empty_passcode_for_username_only(
    fake_conns: list[_FakeConn],
) -> None:
    """A username with no password must still send a passcode header."""
    adapter = StompActiveMqAdapter(AsbConfig(username="vi"))
    adapter.connect()
    assert fake_conns[0].connect_kwargs["passcode"] == ""


# --- session wiring -------------------------------------------------------


def test_connect_passes_host_port_and_heartbeats(
    fake_conns: list[_FakeConn],
) -> None:
    adapter = StompActiveMqAdapter(
        AsbConfig(host="broker.internal", stomp_port=61614, heartbeat_ms=5000)
    )
    adapter.connect()
    init = fake_conns[0].init_kwargs
    assert init["host_and_ports"] == [("broker.internal", 61614)]
    assert init["heartbeats"] == (5000, 5000)


def test_connect_disables_heartbeats_when_zero(
    fake_conns: list[_FakeConn],
) -> None:
    adapter = StompActiveMqAdapter(AsbConfig(heartbeat_ms=0))
    adapter.connect()
    assert fake_conns[0].init_kwargs["heartbeats"] == (0, 0)


def test_subscribe_registers_primary_and_none_alias(
    fake_conns: list[_FakeConn],
) -> None:
    adapter = StompActiveMqAdapter(AsbConfig())
    adapter.connect()
    adapter.subscribe("MA_FlightCommand")
    dests = [s["destination"] for s in fake_conns[0].subscriptions]
    assert dests == [
        "/topic/MA_FlightCommand",
        "/topic/MA_FlightCommand<None>",
    ]


def test_subscribe_before_connect_raises() -> None:
    adapter = StompActiveMqAdapter(AsbConfig())
    with pytest.raises(RuntimeError, match="not connected"):
        adapter.subscribe("MA_FlightCommand")


def test_publish_sends_xml_to_the_topic(
    fake_conns: list[_FakeConn],
) -> None:
    adapter = StompActiveMqAdapter(AsbConfig())
    adapter.connect()
    adapter.publish("ServiceStatus", b"<ServiceStatus/>")
    sent = fake_conns[0].sent[0]
    assert sent["destination"] == "/topic/ServiceStatus"
    assert sent["body"] == "<ServiceStatus/>"
    assert sent["headers"] == {"content-type": "text/xml"}


def test_publish_drops_when_session_is_down() -> None:
    """Isolator keeps ticking through an outage; publish must not raise."""
    adapter = StompActiveMqAdapter(AsbConfig())
    adapter.publish("ServiceStatus", "<ServiceStatus/>")


def test_disconnect_suppresses_reconnect(
    fake_conns: list[_FakeConn],
) -> None:
    adapter = StompActiveMqAdapter(AsbConfig())
    adapter.connect()
    adapter.disconnect()
    assert fake_conns[0].disconnected
    adapter.schedule_reconnect()
    assert len(fake_conns) == 1
