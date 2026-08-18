"""In-process :class:`AsbPort` with no broker.

Used by Isolator unit tests and ``open-vi --memory``. Topic names match
the STOMP adapter (``/topic/<MessageType>`` plus the harness
``<None>`` subscribe alias). Publish records XML by message type and,
when the destination is subscribed, delivers it to ``on_message``
handlers on the calling thread.
"""

from __future__ import annotations

import logging
import threading
import time
from collections import defaultdict, deque

from open_vi.asb.port import MessageHandler
from open_vi.asb.topics import (
    message_type_from_dest,
    subscribe_aliases,
    topic_dest,
)

LOGGER = logging.getLogger(__name__)


class InMemoryAsb:
    """Loopback :class:`AsbPort` for tests and broker-less CLI.

    ``published`` is a per-message-type deque of XML bodies — the log
    Isolator tests assert against. ``wait_for`` polls that log without
    consuming it. ``subscribe`` registers both ``/topic/<MT>`` and
    ``/topic/<MT><None>``.

    Until anything is subscribed, every publish still reaches handlers
    so tests that never call ``subscribe`` still loop back. After the
    first subscription, only matching destinations dispatch.
    ``publish`` raises if ``connect`` has not been called.
    """

    def __init__(self) -> None:
        self._handlers: list[MessageHandler] = []
        self.published: dict[str, deque[str]] = defaultdict(deque)
        self.subscriptions: set[str] = set()
        self.connected = False
        self._lock = threading.Lock()

    def on_message(self, handler: MessageHandler) -> None:
        """Register ``(message_type, xml) → None``. Called from ``publish``."""
        self._handlers.append(handler)

    def connect(self) -> None:
        """Mark the port ready. Required before ``publish``."""
        self.connected = True

    def disconnect(self) -> None:
        """Mark the port closed. Further ``publish`` calls raise."""
        self.connected = False

    def subscribe(self, message_type: str) -> None:
        """Listen for a UCI type and its ``<None>`` harness alias."""
        for dest in subscribe_aliases(message_type):
            self.subscriptions.add(dest)
        LOGGER.debug("InMemoryAsb subscribe %s", message_type)

    def publish(self, message_type: str, xml: str | bytes) -> None:
        """Record *xml* under *message_type* and dispatch if subscribed.

        Always appends to ``published``. Handlers run only when the
        destination matches a subscription, or when the subscription
        set is still empty.
        """
        if not self.connected:
            raise RuntimeError("ASB not connected")
        body = xml.decode("utf-8") if isinstance(xml, bytes) else xml
        dest = topic_dest(message_type)
        mt = message_type_from_dest(dest)
        with self._lock:
            self.published[mt].append(body)
        if self._is_subscribed(dest) or not self.subscriptions:
            for handler in list(self._handlers):
                handler(mt, body)

    def wait_for(self, message_type: str, timeout: float = 2.0) -> str | None:
        """Return the first recorded body for *message_type*, or ``None``.

        Polls ``published`` until *timeout* seconds. Does not pop the
        body — later asserts can still inspect the same queue.
        """
        mt = message_type_from_dest(topic_dest(message_type))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self.published[mt]:
                    return self.published[mt][0]
            time.sleep(0.01)
        return None

    def _is_subscribed(self, destination: str) -> bool:
        """True when *destination* matches any registered subscribe alias."""
        for sub in self.subscriptions:
            if self._match(destination, sub):
                return True
        return False

    @staticmethod
    def _match(published: str, subscribed: str) -> bool:
        """Exact destination match, or same topic ignoring a ``<…>`` suffix."""
        if published == subscribed:
            return True
        base_pub = published.split("<", 1)[0]
        base_sub = subscribed.split("<", 1)[0]
        return base_pub == base_sub
