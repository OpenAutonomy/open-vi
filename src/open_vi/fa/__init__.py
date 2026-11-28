"""Flight Autonomy: the decisions that sit between Isolator and a vehicle.

Scope and the reasoning behind the boundary are in
docs/FLIGHT_AUTONOMY.md. Two rules matter when adding to this package,
and ``tests/test_architecture.py`` enforces the first:

* ``fa`` imports no codec and no bus. It takes domain values and the
  platform port, and returns domain values. That is what would make a
  later extraction into its own repository a move rather than a
  rewrite.
* No product name belongs here. FA decides from capabilities the
  adapter reports, never from which autopilot is attached.
"""

from __future__ import annotations

from open_vi.fa.airfields import (
    AirfieldStoreError,
    default_store_path,
    load_airfields,
)

__all__ = ["AirfieldStoreError", "default_store_path", "load_airfields"]
