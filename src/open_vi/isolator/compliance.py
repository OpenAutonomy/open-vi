"""``COMPLIANCE_MODE`` selects status-ladder length, nothing else.

Handlers stay shared. ``loose`` (the default) publishes
``PROCESSING`` then ``COMPLETED``. ``strict`` inserts ``QUEUED``
first. Route activation, query replies, and control assignment all
walk this ladder. The mode is not an access-control switch.
"""

from __future__ import annotations

from open_vi.isolator.context import IsolatorContext


def is_strict(ctx: IsolatorContext) -> bool:
    """True only when ``compliance_mode`` is ``strict`` (case-insensitive).

    Any other value, including the default ``loose``, is treated as
    loose.
    """
    return ctx.config.compliance_mode.strip().lower() == "strict"


def status_ladder(ctx: IsolatorContext) -> tuple[str, ...]:
    """Command-status states to publish, in order, for the current mode.

    Strict: ``QUEUED``, ``PROCESSING``, ``COMPLETED``.
    Loose: ``PROCESSING``, ``COMPLETED``.
    """
    if is_strict(ctx):
        return ("QUEUED", "PROCESSING", "COMPLETED")
    return ("PROCESSING", "COMPLETED")
