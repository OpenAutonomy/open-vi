"""Compliance-mode helpers (Loose vs Strict OPT branches)."""

from __future__ import annotations

from open_vi.isolator.context import IsolatorContext


def is_strict(ctx: IsolatorContext) -> bool:
    """True when Isolator is running COMPLIANCE_MODE=strict."""
    return ctx.config.compliance_mode.strip().lower() == "strict"


def status_ladder(ctx: IsolatorContext) -> tuple[str, ...]:
    """Status ladder for route activation and query replies."""
    if is_strict(ctx):
        return ("QUEUED", "PROCESSING", "COMPLETED")
    return ("PROCESSING", "COMPLETED")
