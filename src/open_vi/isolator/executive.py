"""VI OMS Isolator executive — A-GRA face on AsbPort."""

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
from open_vi.isolator.publishers import (
    MT_COMPONENT_STATUS,
    MT_CONTROL_STATUS,
    MT_FLIGHT_CAPABILITY,
    MT_FLIGHT_CAPABILITY_STATUS,
    MT_NAVIGATION_REPORT,
    MT_POSITION_REPORT_DETAILED,
    MT_RESPONSE_PLAN_EXECUTION_STATUS,
    MT_WEATHER_OBSERVATION,
)
from open_vi.isolator.state import IsolatorState
from open_vi.platform.port import PlatformPort
from open_vi.platform.stub import StubPlatform

LOGGER = logging.getLogger(__name__)

# Re-export publish MT names used by tests.
__all__ = [
    "Isolator",
    "MT_COMPONENT_STATUS",
    "MT_CONTROL_STATUS",
    "MT_FLIGHT_CAPABILITY",
    "MT_FLIGHT_CAPABILITY_STATUS",
    "MT_NAVIGATION_REPORT",
    "MT_POSITION_REPORT_DETAILED",
    "MT_RESPONSE_PLAN_EXECUTION_STATUS",
    "MT_WEATHER_OBSERVATION",
]


class Isolator:
    """Advertise control, commands, TSPI, routes, contingencies, status."""

    def __init__(
        self,
        bus: AsbPort,
        *,
        platform: PlatformPort | None = None,
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
            platform=platform or StubPlatform(),
            identity=self.identity,
            config=self.config,
            state=IsolatorState(),
        )
        self._handlers: list[MessageHandler] = (
            list(handlers) if handlers is not None else default_handlers()
        )
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._attached = False

    @property
    def inbound_mts(self) -> tuple[str, ...]:
        """Message types subscribed from the current handler set."""
        return collect_inbound_mts(self._handlers)

    def add_handler(self, handler: MessageHandler) -> None:
        self._handlers.append(handler)
        if self._attached:
            for mt in getattr(handler, "inbound_mts", ()):
                self.ctx.bus.subscribe(mt)

    def attach(self) -> None:
        """Connect bus, register dispatch, subscribe inbound MTs (no tick)."""
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
        """Public inbound dispatch (same path as the live bus callback)."""
        for handler in self._handlers:
            if handler.handles(message_type):
                try:
                    handler.handle(message_type, xml, self.ctx)
                except Exception:  # pylint: disable=broad-exception-caught
                    LOGGER.exception("handler failed for %s", message_type)
                return
        LOGGER.warning("no handler for %s", message_type)

    def start(self) -> None:
        """Attach, advertise control, and start the tick loop."""
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
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self.ctx.bus.disconnect()
        self._attached = False
        LOGGER.info("Isolator stopped")

    def run_forever(self) -> None:
        """Block until interrupted; for CLI use."""
        self.start()
        try:
            while not self._stop.is_set():
                time.sleep(0.2)
        except KeyboardInterrupt:
            LOGGER.info("Interrupted")
        finally:
            self.stop()

    def advertise_once(self) -> None:
        """Publish capability + status without running the tick loop (tests)."""
        self._advertise_control()

    def publish_status_package_once(self) -> None:
        """Publish ControlStatus, execution status, and SubsystemStatus."""
        publishers.publish_status_package(self.ctx)

    def publish_contingency(self, kind: str) -> None:
        """Inject a Stub contingency and publish Loose Direction1 outs."""
        publishers.publish_contingency(self.ctx, kind)

    def publish_vehicle_state_once(self) -> None:
        """Publish the five Receive Vehicle State Data outs."""
        publishers.publish_vehicle_state(self.ctx)

    def _advertise_control(self) -> None:
        publishers.advertise_control(self.ctx)

    def _tick_loop(self) -> None:
        period = self.config.tick_period_s
        while not self._stop.wait(period):
            try:
                self._tick()
            except Exception:  # pylint: disable=broad-exception-caught
                LOGGER.exception("Isolator tick failed")

    def _tick(self) -> None:
        """Refresh capability status and publish vehicle-state outs."""
        snap = self.ctx.platform.snapshot()
        if self.ctx.state.last_availability != snap.readiness.availability:
            self._advertise_control()
        elif self.config.tick_republish_status:
            publishers.publish_capability_status(self.ctx)
        if self.config.publish_status_package:
            self.publish_status_package_once()
        if self.config.publish_vehicle_state:
            self.publish_vehicle_state_once()
