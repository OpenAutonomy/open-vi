"""Isolator: A-GRA sequences on :class:`AsbPort` and :class:`PlatformPort`.

This is the only component that owns inbound dispatch, the tick loop,
and outbound advertise / status / TSPI. Handlers parse UCI XML, call
``RouteStore`` and/or the platform, and publish replies. Isolator
never imports STOMP, ActiveMQ, MAVLink, PX4, or Stub.
"""

from __future__ import annotations

import logging
import queue
import threading
import time

from open_vi.asb.port import AsbPort
from open_vi.codec.route import build_sample_route_plan
from open_vi.config import IsolatorConfig
from open_vi.domain import HomeAirfield, home_airfield_from_tspi
from open_vi.identity import SystemIdentity
from open_vi.isolator import publishers
from open_vi.isolator.context import IsolatorContext
from open_vi.isolator.handlers import collect_inbound_mts, default_handlers
from open_vi.isolator.handlers.control import unpair_if_unavailable
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
    optional status package and vehicle-state outs, and runs the
    Isolator thread. That thread is the only live writer: inbound is
    queued onto it, and the tick runs there. Tests that need inbound
    only call ``attach``; tests that need capability on the bus call
    ``advertise_once``. Those entry points take the same session lock
    so a test ``dispatch`` cannot race a test ``_tick``. Construction
    preloads home takeoff and landing ``MA_RoutePlan`` into the store.
    """

    def __init__(
        self,
        bus: AsbPort,
        *,
        platform: PlatformPort,
        config: IsolatorConfig | None = None,
    ) -> None:
        self.config = config or IsolatorConfig()
        self.identity = SystemIdentity.named(
            self.config.system_name,
            self.config.system_label,
            namespace_name=self.config.namespace_name,
            namespace_uuid_id=self.config.namespace_uuid,
        )
        airfield = home_airfield_from_tspi(
            self.identity, platform.get_vehicle_state()
        )
        routes = RouteStore()
        _preload_home_routes(
            self.identity,
            routes,
            airfield,
            schema_version=self.config.schema_version,
            mode=self.config.message_mode,
        )
        self.ctx = IsolatorContext(
            bus=bus,
            platform=platform,
            identity=self.identity,
            config=self.config,
            state=IsolatorState(),
            routes=routes,
            airfield=airfield,
        )
        self._handlers = default_handlers()
        self._session = threading.RLock()
        self._inbound: queue.SimpleQueue[tuple[str, str]] = queue.SimpleQueue()
        self._wakeup = threading.Event()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._attached = False

    @property
    def inbound_mts(self) -> tuple[str, ...]:
        """Unique inbound message types declared on the current handlers."""
        return collect_inbound_mts(self._handlers)

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

        Same path as the live bus callback. After ``start``, the body
        is queued onto the Isolator thread so inbound and tick cannot
        interleave. Before ``start`` (tests), the handler runs here
        under the session lock. Handler exceptions are logged so one
        fault cannot drop the rest of the session. Unknown types are
        logged and ignored.
        """
        if self._on_isolator_thread():
            self._dispatch_locked(message_type, xml)
            return
        if self._isolator_thread_running():
            self._inbound.put((message_type, xml))
            self._wakeup.set()
            return
        self._dispatch_locked(message_type, xml)

    def _isolator_thread_running(self) -> bool:
        """True when the Isolator thread is alive (live ``start`` path)."""
        thread = self._thread
        return thread is not None and thread.is_alive()

    def _on_isolator_thread(self) -> bool:
        """True when the caller is already the Isolator thread."""
        thread = self._thread
        return thread is not None and threading.current_thread() is thread

    def _dispatch_locked(self, message_type: str, xml: str) -> None:
        """Run one handler under the session lock."""
        with self._session:
            self._dispatch_unlocked(message_type, xml)

    def _dispatch_unlocked(self, message_type: str, xml: str) -> None:
        """Run one handler. Caller holds ``_session`` or is the sole writer."""
        for handler in self._handlers:
            if handler.handles(message_type):
                try:
                    handler.handle(message_type, xml, self.ctx)
                except Exception:  # pylint: disable=broad-exception-caught
                    LOGGER.exception("handler failed for %s", message_type)
                return
        LOGGER.warning("no handler for %s", message_type)

    def _drain_inbound(self) -> None:
        """Handle queued inbound bodies on the Isolator thread."""
        while True:
            try:
                message_type, xml = self._inbound.get_nowait()
            except queue.Empty:
                return
            self._dispatch_locked(message_type, xml)

    def start(self) -> None:
        """Attach, advertise, publish optional startup outs, and tick.

        Startup outs run under the session lock on this thread. After
        the Isolator thread starts, inbound is queued onto it.

        Raises ``RuntimeError`` if the Isolator thread is already
        running — including a prior ``stop`` that did not finish
        within its join timeout. Starting a second thread here would
        have it share ``_stop``/``_wakeup`` with the still-running
        one: clearing those would let the old thread's loop condition
        go true again once it finally does return, so it keeps
        looping alongside the new thread instead of exiting.
        """
        if self._isolator_thread_running():
            raise RuntimeError(
                "Isolator is already started, or a previous stop() has "
                "not finished; call stop() first"
            )
        self.attach()
        with self._session:
            self._advertise_control()
            if self.config.publish_status_package:
                publishers.publish_status_package(self.ctx)
            if self.config.publish_vehicle_state:
                publishers.publish_vehicle_state(self.ctx)
        self._stop.clear()
        self._wakeup.clear()
        self._thread = threading.Thread(
            target=self._tick_loop, name="open-vi-isolator", daemon=True
        )
        self._thread.start()
        LOGGER.info(
            "Isolator started system=%s capability=%s",
            self.identity.name,
            self.ctx.state.capability_id.hex,
        )

    def stop(self, *, timeout: float = 2.0) -> None:
        """Stop the Isolator thread, disconnect the bus, clear attach.

        If the thread does not stop within *timeout*, it is left
        running and still tracked on ``_thread`` (not cleared), so a
        later ``start`` refuses to spawn a second thread rather than
        racing the stuck one. The bus is disconnected either way.
        """
        self._stop.set()
        self._wakeup.set()
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            if thread.is_alive():
                LOGGER.error(
                    "Isolator thread did not stop within %.1fs; leaving "
                    "it tracked so start() refuses to run a second one",
                    timeout,
                )
            else:
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
        with self._session:
            self._advertise_control()

    def publish_status_package_once(self) -> None:
        """Publish ControlStatus, execution status, and SubsystemStatus."""
        with self._session:
            publishers.publish_status_package(self.ctx)

    def publish_faults_once(self) -> None:
        """Publish ``MA_Fault`` from the platform fault list."""
        with self._session:
            publishers.publish_faults(self.ctx)

    def publish_subsystem_status_once(self) -> None:
        """Publish ``SubsystemStatus`` from the platform."""
        with self._session:
            publishers.publish_subsystem_status(self.ctx)

    def publish_capability_status_once(self) -> None:
        """Publish ``MA_FlightCapabilityStatus`` only."""
        with self._session:
            publishers.publish_capability_status(self.ctx)

    def publish_flight_capability_once(self) -> None:
        """Publish ``MA_FlightCapability`` only."""
        with self._session:
            publishers.publish_flight_capability(self.ctx)

    def publish_vehicle_state_once(self) -> None:
        """Publish the five Receive Vehicle State Data outs."""
        with self._session:
            publishers.publish_vehicle_state(self.ctx)

    def publish_command_updates_once(self) -> None:
        """Apply session transitions, then publish command completions.

        Route-sourced ``COMPLETED`` calls ``execution.complete`` before
        emit so plan-execution outs see that state. Route-sourced
        ``FAILED`` / ``CANCELED`` abort the live route after emit
        (no ``MA_FlightCommandStatus``). After emit, a ``COMPLETED``
        platform activity calls ``flight.clear``.
        """
        with self._session:
            self._publish_command_updates()

    def _publish_command_updates(self) -> None:
        """Command-completion transitions. Caller holds ``_session``."""
        updates = self.ctx.platform.poll_command_updates()
        for command_id, result in updates:
            if (
                self.ctx.execution.is_sourced(command_id)
                and result.processing_state == "COMPLETED"
            ):
                self.ctx.execution.complete()
        publishers.publish_command_updates(self.ctx, updates)
        for command_id, result in updates:
            if self.ctx.execution.is_sourced(
                command_id
            ) and result.processing_state in {"FAILED", "CANCELED"}:
                self._abort_executing_route()
        for result in (pair[1] for pair in updates):
            if result.processing_state != "COMPLETED":
                continue
            activity = self.ctx.platform.active_flight_activity()
            if activity is not None and activity.activity_state == "COMPLETED":
                self.ctx.flight.clear()

    def _abort_executing_route(self) -> None:
        """VI-initiated abort: FAILED execution, DEACTIVATED, then clear.

        Used when the platform reports the route-sourced command as
        ``FAILED`` or ``CANCELED``. Does not send CANCEL. There is no
        inbound command status.
        """
        ctx = self.ctx
        plan_id = ctx.execution.plan_id
        if plan_id is None:
            return
        stored = ctx.routes.get(plan_id)
        mission_id = stored.mission_plan_id if stored is not None else None
        ctx.execution.mark_failed()
        publishers.publish_plan_execution(ctx)
        ctx.routes.commit(plan_id, "DEACTIVATED")
        if mission_id is not None:
            publishers.publish_mission_plan_activation_status(
                ctx,
                mission_plan_id=mission_id,
                plan_activation_state="DEACTIVATED",
                route_plan_id=plan_id,
            )
        ctx.execution.clear()
        ctx.flight.clear()
        LOGGER.info("VI abort route %s → DEACTIVATED", plan_id.hex)

    def _advertise_control(self) -> None:
        """Publish MA_FlightCapability and MA_FlightCapabilityStatus."""
        publishers.advertise_control(self.ctx)

    def _tick_loop(self) -> None:
        """Drain inbound, then ``_tick`` every ``tick_period_s``.

        Inbound wakes the wait so a command is not delayed until the
        next period. Log and keep going on tick error.
        """
        period = self.config.tick_period_s
        next_tick = time.monotonic() + period
        while not self._stop.is_set():
            self._drain_inbound()
            remaining = next_tick - time.monotonic()
            if remaining <= 0:
                try:
                    self._tick()
                except Exception:  # pylint: disable=broad-exception-caught
                    LOGGER.exception("Isolator tick failed")
                next_tick = time.monotonic() + period
                continue
            self._wakeup.wait(timeout=remaining)
            self._wakeup.clear()

    def _tick(self) -> None:
        """One period: command completions, control offer, status, TSPI.

        Republishes capability when availability changes, or on every
        tick when ``tick_republish_status`` is set, so a late harness
        subscriber still sees the control-mode authorization. When
        the offer is not ``AVAILABLE``, unpairs an acquired
        controller (§1.2.2.8).
        """
        with self._session:
            self._publish_command_updates()
            snap = self.ctx.platform.snapshot()
            if (
                self.ctx.state.last_availability != snap.readiness.availability
                or self.config.tick_republish_status
            ):
                # Republish offer+status so a late harness subscriber
                # still sees control-mode authorization (not only the
                # initial advertise).
                self._advertise_control()
            unpair_if_unavailable(self.ctx, snap.readiness.availability)
            if self.config.publish_status_package:
                publishers.publish_status_package(self.ctx)
            if self.config.publish_vehicle_state:
                publishers.publish_vehicle_state(self.ctx)


def _preload_home_routes(
    identity: SystemIdentity,
    routes: RouteStore,
    airfield: HomeAirfield,
    *,
    schema_version: str,
    mode: str,
) -> None:
    """Ingest takeoff and landing plans linked to *airfield*."""
    for route_id, path_type, points in (
        (airfield.takeoff_route_id, "TAKEOFF", airfield.takeoff_path),
        (airfield.landing_route_id, "LANDING", airfield.landing_path),
    ):
        xml = build_sample_route_plan(
            identity,
            route_plan_id=route_id,
            waypoints=points,
            path_type=path_type,
            airfield_id=airfield.airfield_id,
            runway_id=airfield.runway_id,
            schema_version=schema_version,
            mode=mode,
        )
        routes.ingest(route_id, xml.decode("utf-8"))
