"""STOMP client adapter for ActiveMQ Classic as the ASB."""

from __future__ import annotations

import logging
import threading
import time

import stomp
from stomp.utils import Frame

from open_vi.asb.port import MessageHandler
from open_vi.asb.topics import (
    message_type_from_dest,
    subscribe_aliases,
    topic_dest,
)
from open_vi.config import AsbConfig

LOGGER = logging.getLogger(__name__)


class _Listener(stomp.ConnectionListener):
    """Forward STOMP callbacks into :class:`StompActiveMqAdapter`."""

    def __init__(self, owner: StompActiveMqAdapter) -> None:
        self._owner = owner

    def on_error(self, frame: Frame) -> None:
        LOGGER.error("ASB error: %s", getattr(frame, "body", frame))

    def on_disconnected(self) -> None:
        LOGGER.warning("ASB disconnected")
        self._owner.schedule_reconnect()

    def on_message(self, frame: Frame) -> None:
        headers = getattr(frame, "headers", {}) or {}
        dest = headers.get("destination", headers.get("Destination", ""))
        body = frame.body
        if isinstance(body, bytes):
            body = body.decode("utf-8", errors="replace")
        self._owner.dispatch_message(dest, body or "")


class StompActiveMqAdapter:
    """:class:`AsbPort` backed by ActiveMQ STOMP."""

    def __init__(self, config: AsbConfig | None = None) -> None:
        self.config = config or AsbConfig()
        self._handlers: list[MessageHandler] = []
        self._conn: stomp.Connection | None = None
        self._sub_id = 0
        self._message_types: list[str] = []
        self._closing = False
        self._reconnect_lock = threading.Lock()
        self._reconnect_thread: threading.Thread | None = None

    def on_message(self, handler: MessageHandler) -> None:
        self._handlers.append(handler)

    def connect(self) -> None:
        self._closing = False
        host_and_ports = [(self.config.host, self.config.stomp_port)]
        hb = self.config.heartbeat_ms
        conn = stomp.Connection(
            host_and_ports=host_and_ports,
            heartbeats=(hb, hb) if hb > 0 else (0, 0),
            try_loopback_connect=False,
        )
        conn.set_listener("open_vi", _Listener(self))
        kw: dict = {"wait": True}
        if self.config.username:
            kw["username"] = self.config.username
            kw["passcode"] = self.config.password or ""
        conn.connect(**kw)
        self._conn = conn
        LOGGER.info(
            "Connected to ASB %s:%s", self.config.host, self.config.stomp_port
        )

    def disconnect(self) -> None:
        self._closing = True
        if self._conn is not None:
            try:
                self._conn.disconnect()
            except Exception:  # pylint: disable=broad-exception-caught
                # stomp.py may raise assorted errors while tearing down.
                LOGGER.debug("disconnect failed", exc_info=True)
            self._conn = None

    def subscribe(self, message_type: str) -> None:
        if message_type not in self._message_types:
            self._message_types.append(message_type)
        for dest in subscribe_aliases(message_type):
            self._subscribe_dest(dest)

    def _subscribe_dest(self, destination: str) -> None:
        if self._conn is None:
            raise RuntimeError("ASB not connected")
        self._sub_id += 1
        self._conn.subscribe(
            destination=destination, id=str(self._sub_id), ack="auto"
        )
        LOGGER.info("Subscribed %s", destination)

    def publish(self, message_type: str, xml: str | bytes) -> None:
        conn = self._conn
        if conn is None or not conn.is_connected():
            LOGGER.warning(
                "publish dropped (ASB not connected): %s", message_type
            )
            return
        body = xml.decode("utf-8") if isinstance(xml, bytes) else xml
        dest = topic_dest(message_type)
        conn.send(
            destination=dest, body=body, headers={"content-type": "text/xml"}
        )
        LOGGER.info("Published %s (%s bytes)", dest, len(body))

    def schedule_reconnect(self) -> None:
        """Start a background reconnect attempt if not already running."""
        if self._closing:
            return
        with self._reconnect_lock:
            if (
                self._reconnect_thread is not None
                and self._reconnect_thread.is_alive()
            ):
                return
            self._reconnect_thread = threading.Thread(
                target=self._reconnect_loop, daemon=True
            )
            self._reconnect_thread.start()

    def _reconnect_loop(self) -> None:
        delay = 1.0
        while not self._closing:
            time.sleep(delay)
            try:
                self._conn = None
                self._sub_id = 0
                self.connect()
                for mt in list(self._message_types):
                    for dest in subscribe_aliases(mt):
                        self._subscribe_dest(dest)
                LOGGER.info(
                    "ASB reconnected (%s message types)",
                    len(self._message_types),
                )
                return
            except Exception:  # pylint: disable=broad-exception-caught
                # Broker/network failures vary; backoff and retry.
                LOGGER.warning(
                    "ASB reconnect failed; retry in %.0fs", delay, exc_info=True
                )
                delay = min(delay * 2, 15.0)

    def dispatch_message(self, destination: str, body: str) -> None:
        """Deliver one inbound STOMP frame to registered handlers."""
        mt = message_type_from_dest(destination)
        for handler in list(self._handlers):
            try:
                handler(mt, body)
            except Exception:  # pylint: disable=broad-exception-caught
                # Handlers must not take down the STOMP listener thread.
                LOGGER.exception("handler failed for %s", mt)
