"""PlatformPort and vehicle backends."""

from __future__ import annotations

from open_vi.platform.port import PlatformPort
from open_vi.platform.stub import StubPlatform

__all__ = [
    "PlatformPort",
    "StubPlatform",
    "make_platform",
]


def make_platform(
    name: str = "stub",
    *,
    mavlink_url: str | None = None,
    autoconnect: bool = True,
    path_clearance_m: float | None = None,
) -> PlatformPort:
    """Construct a vehicle backend by name (``stub`` or ``px4``)."""
    key = name.strip().lower()
    if key == "stub":
        return StubPlatform()
    if key == "px4":
        # Import PX4 only when selected; package import must not load it.
        # pylint: disable-next=import-outside-toplevel
        from open_vi.platform.px4 import Px4MavlinkAdapter

        return Px4MavlinkAdapter(
            connection_url=mavlink_url,
            autoconnect=autoconnect,
            path_clearance_m=path_clearance_m,
        )
    raise ValueError(f"Unknown platform {name!r}; expected stub|px4")
