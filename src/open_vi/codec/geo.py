"""UCI angle helpers: wire radians ↔ internal degrees."""

from __future__ import annotations

import math


def deg_to_rad(degrees: float) -> float:
    """Convert degrees to radians for UCI Angle* / Point2D fields."""
    return math.radians(degrees)


def rad_to_deg(radians: float) -> float:
    """Convert UCI Angle* / Point2D radians to degrees."""
    return math.degrees(radians)


def format_uci_angle(radians: float) -> str:
    """Serialize a UCI angle (radians) for XML text content."""
    return f"{radians:.9g}"
