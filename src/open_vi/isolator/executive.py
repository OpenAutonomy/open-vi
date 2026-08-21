"""Isolator: A-GRA sequences on :class:`AsbPort` and :class:`PlatformPort`.

This is the only component that owns inbound dispatch, the tick loop,
and outbound advertise / status / TSPI. Handlers parse UCI XML, call
``RouteStore`` and/or the platform, and publish replies. Isolator
never imports STOMP, ActiveMQ, MAVLink, PX4, or Stub.
"""

from __future__ import annotations

import logging
import threading
import time

from open_vi.asb.port import AsbPort
from open_vi.config import IsolatorConfig
from open_vi.identity import SystemIdentity
from open_vi.isolator import publishers
from open_vi.isolator.context import IsolatorContext
from open_vi.isolator.handlers import (
    MessageHandler,
    collect_inbound_mts,
    default_handlers,
)
from open_vi.isolator.routes import RouteStore
from open_vi.isolator.state import IsolatorState
from open_vi.platform.port import PlatformPort

LOGGER = logging.getLogger(__name__)


class Isolator:
    """Connect the bus, dispatch handlers, advertise, and tick.

    ``platform`` is required. There is no default Stub, and this class
    does not import one. ``bus`` is an :class:`AsbPort` — Isolator
    never sees broker types.

    ``attach`` opens the session and subscribes each handler's inbound
    types. ``start`` attaches, advertises control, publishes the
    optional status package and vehicle-state outs, and runs the tick
    loop. Tests that need inbound only call ``attach``; tests that
    need capability on the bus call ``advertise_once``.
    """

    def __init__(
        self,
        bus: AsbPort,
        *,
        platform: PlatformPort,
        config: IsolatorConfig | None = None,
        identity: SystemIdentity | None = None,
        handlers: list[MessageHandler] | None = None,
    ) -> None:
        self.config = config or IsolatorConfig()
        self.identity = identity or SystemIdentity.named(
            self.config.system_name,
            self.config.system_label,
            namespace_name=self.config.namespace_name,
            namespace_uuid_id=self.config.namespace_uuid,
        )
        self.ctx = IsolatorContext(
            bus=bus,
            platform=platform,
            identity=self.identity,
            config=self.config,
            state=IsolatorState(),
            routes=RouteStore(),
        )
        self._handlers: list[MessageHandler] = (
            list(handlers) if handlers is not None else default_handlers()
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._attached = False

    @property
    def inbound_mts(self) -> tuple[str, ...]:
        """Unique inbound message types declared on the current handlers."""
        return collect_inbound_mts(self._handlers)

    def add_handler(self, handler: MessageHandler) -> None:
        """Append a handler.

        If already attached, subscribe its inbound types.
        """
        self._handlers.append(handler)
        if self._attached:
            for mt in getattr(handler, "inbound_mts", ()):
                self.ctx.bus.subscribe(mt)

    def attach(self) -> None:
        """Connect the bus, register ``dispatch``, and subscribe inbound types.

        Does not advertise or start the tick loop. Safe to call twice;
        the second call is a no-op.
        """
        if self._attached:
            return
        bus = self.ctx.bus
        bus.on_message(self.dispatch)
        bus.connect()
        for mt in self.inbound_mts:
            bus.subscribe(mt)
        self._attached = True
        LOGGER.info(
            "Isolator attached inbound_mts=%s", ",".join(self.inbound_mts)
        )

    def dispatch(self, message_type: str, xml: str) -> None:
        """Route one inbound body to the first handler that claims it.

        Same path as the live bus callback. Tests call this directly.
        Handler exceptions are logged so one fault cannot drop the
        rest of the session. Unknown types are logged and ignored.
        """
        for handler in self._handlers:
            if handler.handles(message_type):
                try:
                    handler.handle(message_type, xml, self.ctx)
                except Exception:  # pylint: disable=broad-exception-caught
                    LOGGER.exception("handler failed for %s", message_type)
                return
        LOGGER.warning("no handler for %s", message_type)

    def start(self) -> None:
        """Attach, advertise, publish optional startup outs, and tick."""
        self.attach()
        self._advertise_control()
        if self.config.publish_status_package:
            self.publish_status_package_once()
        if self.config.publish_vehicle_state:
            self.publish_vehicle_state_once()
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._tick_loop, name="open-vi-isolator", daemon=True
        )
        self._thread.start()
        LOGGER.info(
            "Isolator started system=%s capability=%s",
            self.identity.name,
            self.ctx.state.capability_id.hex,
        )

    def stop(self) -> None:
        """Stop the tick loop, disconnect the bus, and clear attach state."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.ctx.bus.disconnect()
        self._attached = False
        LOGGER.info("Isolator stopped")

    def run_forever(self) -> None:
        """``start``, then block until SIGINT or ``stop``. For CLI use."""
        self.start()
        try:
            while not self._stop.is_set():
                time.sleep(0.2)
        except KeyboardInterrupt:
            LOGGER.info("Interrupted")
        finally:
            self.stop()

    def advertise_once(self) -> None:
        """Publish capability and status without starting the tick loop."""
        self._advertise_control()

    def publish_status_package_once(self) -> None:
        """Publish ControlStatus, execution status, and SubsystemStatus."""
        publishers.publish_status_package(self.ctx)

    def publish_contingency(self, kind: str) -> None:
        """Inject a Stub contingency and publish its Loose Direction1 outs.

        Stays off :class:`PlatformPort`. Only meaningful with Stub.
        """
        publishers.publish_contingency(self.ctx, kind)

    def publish_vehicle_state_once(self) -> None:
        """Publish the five Receive Vehicle State Data outs."""
        publishers.publish_vehicle_state(self.ctx)

    def publish_command_updates_once(self) -> None:
        """Apply session transitions, then publish command completions.

        Route-sourced ``COMPLETED`` calls ``execution.complete`` before
        emit so plan-execution outs see that state. After emit, a
        ``COMPLETED`` platform activity calls ``flight.clear``.
        """
        updates = self.ctx.platform.poll_command_updates()
        for command_id, result in updates:
            if (
                self.ctx.execution.is_sourced(command_id)
                and result.processing_state == "COMPLETED"
            ):
                self.ctx.execution.complete()
        publishers.publish_command_updates(self.ctx, updates)
        for result in (pair[1] for pair in updates):
            if result.processing_state != "COMPLETED":
                continue
            activity = self.ctx.platform.active_flight_activity()
            if activity is not None and activity.activity_state == "COMPLETED":
                self.ctx.flight.clear()

    def _advertise_control(self) -> None:
        """Publish MA_FlightCapability and MA_FlightCapabilityStatus."""
        publishers.advertise_control(self.ctx)

    def _tick_loop(self) -> None:
        """Call ``_tick`` every ``tick_period_s``.

        Log and keep going on error.
        """
        period = self.config.tick_period_s
        while not self._stop.wait(period):
            try:
                self._tick()
            except Exception:  # pylint: disable=broad-exception-caught
                LOGGER.exception("Isolator tick failed")

    def _tick(self) -> None:
        """One period: command completions, control offer, status, TSPI.

        Republishes capability when availability changes, or on every
        tick when ``tick_republish_status`` is set, so a late harness
        subscriber still sees the control-mode authorization.
        """
        self.publish_command_updates_once()
        snap = self.ctx.platform.snapshot()
        if (
            self.ctx.state.last_availability != snap.readiness.availability
            or self.config.tick_republish_status
        ):
            # Republish offer+status so a late harness subscriber still sees
            # control-mode authorization (not only the initial advertise).
            self._advertise_control()
        if self.config.publish_status_package:
            self.publish_status_package_once()
        if self.config.publish_vehicle_state:
            self.publish_vehicle_state_once()
