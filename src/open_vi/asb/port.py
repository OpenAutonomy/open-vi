"""Isolator's Abstract Service Bus dependency.

Isolator talks to :class:`AsbPort` only. It never imports STOMP or
ActiveMQ types. ``message_type`` is a UCI/A-GRA root name (for example
``MA_FlightCommand``). Adapters map that to ``/topic/<MessageType>``.
A ``MessageHandler`` is ``(message_type, xml) → None``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

MessageHandler = Callable[[str, str], None]


@runtime_checkable
class AsbPort(Protocol):
    """Connect, subscribe, publish, and receive UCI XML.

    Implementations are :class:`~open_vi.asb.stomp_amq.StompActiveMqAdapter`
    and :class:`~open_vi.asb.memory.InMemoryAsb`. Adapters own destinations
    and the wire; Isolator owns sequences.
    """

    def connect(self) -> None:
        """Open the session. Isolator calls this before subscribe or publish."""

    def disconnect(self) -> None:
        """Close the session."""

    def subscribe(self, message_type: str) -> None:
        """Listen for a UCI type.

        Adapters also register the ``<None>`` alias.
        """

    def publish(self, message_type: str, xml: str | bytes) -> None:
        """Send a UCI XML body for *message_type*."""

    def on_message(self, handler: MessageHandler) -> None:
        """Register ``(message_type, xml) → None`` for inbound traffic."""
