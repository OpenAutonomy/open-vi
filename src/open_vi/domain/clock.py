"""The UCI wire timestamp.

A-GRA ``DateTimeType`` is ISO-8601 with milliseconds and a ``Z``
suffix. This lives in the domain layer because both sides need it and
neither may import the other: the codec writes it into messages, and a
:class:`~open_vi.platform.port.PlatformPort` adapter records it when a
fault appears -- A-GRA's ``DetectionTime`` is explicitly the moment of
detection, not of transmission, so the producer stamps it rather than
the builder.

``open_vi.codec.xmlutil`` re-exports this under its historical name so
its callers are unchanged.
"""

from __future__ import annotations

from datetime import UTC, datetime


def utc_now() -> str:
    """Now, as a UCI ``DateTimeType``: millisecond ISO-8601, ``Z``."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
