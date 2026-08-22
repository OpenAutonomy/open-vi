"""Inbound message handler protocol and shared reply policy."""

from __future__ import annotations

from typing import Protocol

from open_vi.isolator.context import IsolatorContext

STATUS_LADDER = ("QUEUED", "PROCESSING", "COMPLETED")
"""Inbound command-status states for route, query, and control.

DEACTIVATE is the exception: the route handler emits a single status.
Query failure uses QUEUED / PROCESSING / FAILED locally.
"""


class MessageHandler(Protocol):
    """Inbound MT handler.

    Concrete handlers must set ``inbound_mts`` so ``Isolator.attach`` /
    ``start`` subscribe the production topics.
    """

    inbound_mts: tuple[str, ...]

    def handles(self, message_type: str) -> bool: ...

    def handle(
        self, message_type: str, xml: str, ctx: IsolatorContext
    ) -> None: ...
