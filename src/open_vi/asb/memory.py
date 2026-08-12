"""In-memory ASB loopback for unit tests (no broker)."""

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
    """Loopback :class:`AsbPort` implementation."""

    def __init__(self) -> None:
        self._handlers: list[MessageHandler] = []
        self.published: dict[str, deque[str]] = defaultdict(deque)
        self.subscriptions: set[str] = set()
        self.connected = False
        self._lock = threading.Lock()

    def on_message(self, handler: MessageHandler) -> None:
        self._handlers.append(handler)

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def subscribe(self, message_type: str) -> None:
        for dest in subscribe_aliases(message_type):
            self.subscriptions.add(dest)
        LOGGER.debug("InMemoryAsb subscribe %s", message_type)

    def publish(self, message_type: str, xml: str | bytes) -> None:
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
        mt = message_type_from_dest(topic_dest(message_type))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            with self._lock:
                if self.published[mt]:
                    return self.published[mt][0]
            time.sleep(0.01)
        return None

    def _is_subscribed(self, destination: str) -> bool:
        for sub in self.subscriptions:
            if self._match(destination, sub):
                return True
        return False

    @staticmethod
    def _match(published: str, subscribed: str) -> bool:
        if published == subscribed:
            return True
        base_pub = published.split("<", 1)[0]
        base_sub = subscribed.split("<", 1)[0]
        return base_pub == base_sub
