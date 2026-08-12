"""Parse/build QueryDataRequest* (flight-capability query)."""

from __future__ import annotations

from uuid import UUID

from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.xmlutil import (
    el,
    id_type,
    message_envelope,
    system_id,
    tostring,
)
from open_vi.identity import SystemIdentity


def build_query_data_request_status(
    identity: SystemIdentity,
    *,
    request_id: UUID,
    processing_state: str = "COMPLETED",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build QueryDataRequestStatus (Loose: no Result / native pages)."""
    data = el(
        "MessageData",
        id_type("RequestID", request_id),
        el("RequestProcessingState", text=processing_state),
    )
    root = message_envelope(
        "QueryDataRequestStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_sample_query_data_request(
    identity: SystemIdentity,
    *,
    request_id: UUID,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal QueryDataRequest for unit tests."""
    data = el(
        "MessageData",
        id_type("RequestID", request_id),
        el("RequestState", text="NEW"),
        el(
            "QueryMessage",
            el("MessageType", text="MA_FLIGHT_CAPABILITY"),
        ),
        system_id(identity),
    )
    root = message_envelope(
        "QueryDataRequest",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)
