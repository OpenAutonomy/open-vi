"""Transport-agnostic Abstract Service Bus port."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable

# message_type (root MT name), xml body
MessageHandler = Callable[[str, str], None]


@runtime_checkable
class AsbPort(Protocol):
    """Narrow bus face used by Isolator code — no STOMP/AMQ types.

    ``message_type`` is the UCI/A-GRA message type name
    (e.g. ``MA_FlightCommand``). Adapters map that to
    ``/topic/<MessageTypeName>``.
    """

    def connect(self) -> None: ...

    def disconnect(self) -> None: ...

    def subscribe(self, message_type: str) -> None: ...

    def publish(self, message_type: str, xml: str | bytes) -> None: ...

    def on_message(self, handler: MessageHandler) -> None: ...
