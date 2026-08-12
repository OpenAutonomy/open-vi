"""Shared Isolator test helpers (mirrors production attach path)."""

from __future__ import annotations

from open_vi.isolator import Isolator


def attach_isolator(iso: Isolator) -> None:
    """Connect bus + subscribe handler inbound_mts (no tick loop)."""
    iso.attach()
