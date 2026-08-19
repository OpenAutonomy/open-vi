"""Command-status states for route, query, and control replies.

Handlers publish ``QUEUED``, then ``PROCESSING``, then ``COMPLETED``.
DEACTIVATE is the exception: the route handler emits a single status.
"""

from __future__ import annotations

STATUS_LADDER = ("QUEUED", "PROCESSING", "COMPLETED")
