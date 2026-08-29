"""PX4 MAVLink session: connect, reader, arm, mode, QNH, nav params.

A second adapter can reuse :class:`MavlinkLink` for the wire and
leave mission / offboard to its own modules.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from typing import Any

LOGGER = logging.getLogger(__name__)

DEFAULT_MAVLINK_URL = "udpin:127.0.0.1:14540"
_QNH_PARAM = "SENS_BARO_QNH"
_QNH_ACK_TIMEOUT_S = 5.0


class CommandCanceled(Exception):
    """Raised out of a blocking wait when a CANCEL arrives mid-execution."""


class MavlinkLink:
    """One MAVLink connection plus the IO lock the reader shares."""

    def __init__(
        self,
        connection_url: str,
        *,
        heartbeat_timeout_s: float,
        on_message: Callable[[Any], None],
        connection: Any | None = None,
    ) -> None:
        self.connection_url = connection_url
        self._heartbeat_timeout_s = heartbeat_timeout_s
        self._on_message = on_message
        self.conn: Any | None = connection
        self.io_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def connect(self) -> None:
        """Open MAVLink and wait for HEARTBEAT. Does not start the reader.

        pymavlink is imported here so a stub-only install can still
        import this package. Raises ``ImportError`` without the extra,
        ``TimeoutError`` if no heartbeat arrives.
        """
        if self.conn is not None:
            return
        try:
            # Optional dependency: keep import lazy so stub installs work.
            # pylint: disable-next=import-outside-toplevel
            from pymavlink import mavutil
        except ImportError as exc:
            raise ImportError(
                "PX4 backend requires pymavlink; "
                "install with pip install -e '.[px4]'"
            ) from exc
        LOGGER.info("Connecting to PX4 at %s", self.connection_url)
        self.conn = mavutil.mavlink_connection(self.connection_url)
        msg = self.conn.wait_heartbeat(timeout=self._heartbeat_timeout_s)
        if msg is None:
            self.close()
            raise TimeoutError(
                f"No HEARTBEAT from {self.connection_url} within "
                f"{self._heartbeat_timeout_s}s"
            )
        LOGGER.info(
            "PX4 heartbeat system=%s component=%s",
            self.conn.target_system,
            self.conn.target_component,
        )

    def start_reader(self) -> None:
        """Drain inbound MAVLink on a daemon thread."""
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(
            target=self._reader_loop,
            name="open-vi-px4-mavlink",
            daemon=True,
        )
        self._thread.start()

    def close(self) -> None:
        """Stop the reader and close the MAVLink connection."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        conn = self.conn
        self.conn = None
        if conn is not None:
            try:
                conn.close()
            except Exception:  # pylint: disable=broad-exception-caught
                LOGGER.debug("PX4 connection close failed", exc_info=True)

    def require_conn(self) -> Any:
        """Return the open MAVLink connection, or raise if closed."""
        if self.conn is None:
            raise RuntimeError("PX4 not connected")
        return self.conn

    def apply_nav_params(self, clearance_m: float) -> None:
        """Set MC acceptance to *clearance_m*."""
        # pylint: disable-next=import-outside-toplevel
        from pymavlink import mavutil

        conn = self.conn
        if conn is None or not hasattr(conn.mav, "param_set_send"):
            return
        for name, value in (
            ("NAV_ACC_RAD", clearance_m),
            ("NAV_MC_ALT_RAD", clearance_m),
        ):
            conn.mav.param_set_send(
                conn.target_system,
                conn.target_component,
                name.encode("ascii"),
                float(value),
                mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
            )
        LOGGER.info(
            "PX4 nav capture NAV_ACC_RAD=%.0f NAV_MC_ALT_RAD=%.0f",
            clearance_m,
            clearance_m,
        )

    def set_qnh_hpa(self, hpa: float) -> None:
        """PARAM_SET ``SENS_BARO_QNH`` and wait for PARAM_VALUE."""
        # pylint: disable-next=import-outside-toplevel
        from pymavlink import mavutil

        conn = self.require_conn()
        name = _QNH_PARAM.encode("ascii")
        with self.io_lock:
            conn.mav.param_set_send(
                conn.target_system,
                conn.target_component,
                name,
                float(hpa),
                mavutil.mavlink.MAV_PARAM_TYPE_REAL32,
            )
            deadline = time.monotonic() + _QNH_ACK_TIMEOUT_S
            while time.monotonic() < deadline:
                msg = conn.recv_match(
                    type="PARAM_VALUE", blocking=True, timeout=1.0
                )
                if msg is None:
                    continue
                param_id = getattr(msg, "param_id", b"")
                if isinstance(param_id, bytes):
                    param_id = param_id.split(b"\x00", 1)[0].decode(
                        "ascii", errors="replace"
                    )
                if str(param_id).strip("\x00") == _QNH_PARAM:
                    return
        raise TimeoutError("Timed out waiting for SENS_BARO_QNH")

    def set_mode(self, name: str) -> bool:
        """Set a PX4 mode by name. Caller must hold ``io_lock``."""
        conn = self.require_conn()
        mapping = conn.mode_mapping() or {}
        mode = mapping.get(name)
        if mode is None:
            return False
        try:
            if isinstance(mode, tuple) and len(mode) == 3:
                conn.set_mode(mode[0], mode[1], mode[2])
            else:
                conn.set_mode(mode)
        except Exception:  # pylint: disable=broad-exception-caught
            LOGGER.warning("set_mode(%s) failed", name, exc_info=True)
            return False
        return True

    def hold(self) -> None:
        """Leave MISSION before replacing items. Holds ``io_lock``."""
        for name in ("HOLD", "AUTO.LOITER", "LOITER"):
            if self.set_mode(name):
                LOGGER.info("PX4 hold before mission replace (%s)", name)
                return

    def arm(
        self,
        *,
        force: bool,
        is_armed: Callable[[], bool],
        ingest: Callable[[Any], None],
        wait_ack: Callable[[int, float], None],
    ) -> None:
        """Arm motors. Caller must hold ``io_lock``."""
        # pylint: disable-next=import-outside-toplevel
        from pymavlink import mavutil

        if is_armed():
            return
        conn = self.require_conn()
        # param2=21196 forces arm in SITL when prechecks would block.
        force_param = 21196.0 if force else 0.0
        last_error: Exception | None = None
        for _ in range(5):
            conn.mav.command_long_send(
                conn.target_system,
                conn.target_component,
                mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM,
                0,
                1.0,
                force_param,
                0,
                0,
                0,
                0,
                0,
            )
            try:
                wait_ack(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 5.0)
                last_error = None
                break
            except RuntimeError as exc:
                last_error = exc
                if "result=1" not in str(exc):
                    raise
                time.sleep(0.2)
        if last_error is not None:
            raise last_error
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            msg = conn.recv_match(type="HEARTBEAT", blocking=True, timeout=1.0)
            if msg is not None:
                ingest(msg)
            if is_armed():
                LOGGER.info("PX4 armed")
                return
        raise TimeoutError("Timed out waiting for PX4 armed")

    def wait_airborne(
        self,
        alt_m: float,
        *,
        relative_alt_m: Callable[[], float],
        ingest: Callable[[Any], None],
        tick: Callable[[], None] | None = None,
        cancel: threading.Event | None = None,
    ) -> None:
        """Wait until relative altitude shows climb. Holds ``io_lock``.

        Raises :class:`CommandCanceled` as soon as *cancel* is set,
        rather than waiting out the full climb timeout.
        """
        airborne_m = min(5.0, max(2.0, alt_m * 0.25))
        if relative_alt_m() >= airborne_m:
            LOGGER.info("PX4 already airborne; skipping climb wait")
            return
        conn = self.require_conn()
        deadline = time.monotonic() + 60.0
        while time.monotonic() < deadline:
            if cancel is not None and cancel.is_set():
                raise CommandCanceled("wait_airborne canceled")
            if tick is not None:
                tick()
            msg = conn.recv_match(blocking=True, timeout=0.1)
            if msg is not None:
                ingest(msg)
            if relative_alt_m() >= airborne_m:
                LOGGER.info(
                    "PX4 airborne relative_alt=%.1fm (target=%.1fm)",
                    relative_alt_m(),
                    alt_m,
                )
                return
        raise TimeoutError(
            "Timed out waiting for takeoff "
            f"(rel_alt={relative_alt_m():.1f}m target={alt_m:.1f}m)"
        )

    def wait_command_ack(self, command: int, timeout: float = 5.0) -> None:
        """Block until COMMAND_ACK for *command*. Caller holds ``io_lock``."""
        conn = self.require_conn()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            msg = conn.recv_match(
                type="COMMAND_ACK", blocking=True, timeout=1.0
            )
            if msg is None:
                continue
            if int(getattr(msg, "command", -1)) != int(command):
                continue
            result = int(getattr(msg, "result", -1))
            # MAV_RESULT_ACCEPTED = 0, IN_PROGRESS = 5
            if result in (0, 5):
                return
            raise RuntimeError(f"COMMAND_ACK command={command} result={result}")
        raise TimeoutError(f"No COMMAND_ACK for command={command}")

    def _reader_loop(self) -> None:
        """Drain MAVLink into ``on_message`` until ``close``."""
        assert self.conn is not None
        while not self._stop.wait(0.01):
            try:
                with self.io_lock:
                    msg = self.conn.recv_match(blocking=False)
            except Exception:  # pylint: disable=broad-exception-caught
                LOGGER.exception("PX4 recv_match failed")
                continue
            if msg is None:
                continue
            self._on_message(msg)
