"""PX4 / SITL vehicle backend.

``Px4MavlinkAdapter`` is the :class:`~open_vi.platform.port.PlatformPort`.
Link, mission, offboard, and telemetry live in sibling modules so a
second adapter can reuse them. Isolator never imports this package —
``make_platform("px4")`` loads it.
"""

from open_vi.platform.px4.adapter import Px4MavlinkAdapter
from open_vi.platform.px4.mission import advance_mission_waypoints

__all__ = [
    "Px4MavlinkAdapter",
    "advance_mission_waypoints",
]
