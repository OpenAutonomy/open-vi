"""Inbound message handler protocol."""

from __future__ import annotations

from typing import Protocol

from open_vi.isolator.context import IsolatorContext


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
