"""In-memory ASB port tests (no broker)."""

from __future__ import annotations

from open_vi.asb import InMemoryAsb, topic_dest
from open_vi.asb.port import AsbPort


def test_inmemory_is_asb_port() -> None:
    bus = InMemoryAsb()
    assert isinstance(bus, AsbPort)


def test_topic_dest() -> None:
    assert topic_dest("MA_FlightCommand") == "/topic/MA_FlightCommand"
    assert topic_dest("/topic/MA_FlightCommand") == "/topic/MA_FlightCommand"


def test_publish_subscribe_loopback() -> None:
    bus = InMemoryAsb()
    seen: list[tuple[str, str]] = []

    bus.on_message(lambda mt, body: seen.append((mt, body)))
    bus.connect()
    bus.subscribe("MA_FlightCommand")
    bus.publish("MA_FlightCommand", "<MA_FlightCommand/>")

    assert seen == [("MA_FlightCommand", "<MA_FlightCommand/>")]
    assert (
        bus.wait_for("MA_FlightCommand", timeout=0.1) == "<MA_FlightCommand/>"
    )


def test_publish_requires_connect() -> None:
    bus = InMemoryAsb()
    try:
        bus.publish("MA_FlightCommand", "<x/>")
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass


def test_dual_alias_subscribe_matches() -> None:
    bus = InMemoryAsb()
    seen: list[str] = []
    bus.on_message(lambda mt, _body: seen.append(mt))
    bus.connect()
    bus.subscribe("MA_PositionReportDetailed")
    bus.publish("MA_PositionReportDetailed", "<MA_PositionReportDetailed/>")
    assert seen == ["MA_PositionReportDetailed"]
