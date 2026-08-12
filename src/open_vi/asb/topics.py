"""ASB topic naming for A-GRA / harness-compatible destinations."""

from __future__ import annotations


def topic_dest(message_type: str) -> str:
    """STOMP destination for a UCI/A-GRA message type name."""
    name = message_type.strip()
    if name.startswith("/topic/"):
        return name.split("<", 1)[0]
    return f"/topic/{name}"


def message_type_from_dest(destination: str) -> str:
    """Best-effort MT name from a STOMP destination."""
    dest = destination.strip()
    if dest.startswith("/topic/"):
        dest = dest[len("/topic/") :]
    return dest.split("<", 1)[0]


def subscribe_aliases(message_type: str) -> list[str]:
    """Primary topic plus harness-style ``<None>`` alias."""
    primary = topic_dest(message_type)
    return [primary, f"{primary}<None>"]
