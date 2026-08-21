"""Live flight activity session owned by Isolator.

:class:`FlightSession` holds the one activity MA may name on
Activity UPDATE. Handlers and the tick call :meth:`begin` and
:meth:`clear`. Publishers only read ``activity_id``.
"""

from __future__ import annotations

from uuid import UUID


class FlightSession:
    """The live Isolator activity, or idle when ``activity_id`` is None.

    Capability NEW and route ACTIVATE call :meth:`begin`. Route
    DEACTIVATE and a tick that sees a ``COMPLETED`` platform activity
    call :meth:`clear`.
    """

    def __init__(self) -> None:
        self.activity_id: UUID | None = None

    def begin(self, activity_id: UUID) -> None:
        """Record *activity_id* as the live activity."""
        self.activity_id = activity_id

    def clear(self) -> None:
        """Return to idle. Activity UPDATE will reject until :meth:`begin`."""
        self.activity_id = None
