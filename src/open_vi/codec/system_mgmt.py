"""Parse/build MA_SystemManagementRequest* (barometric / QNH)."""

from __future__ import annotations

from uuid import UUID

from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.status import service_id_element
from open_vi.codec.xmlutil import (
    el,
    find_text,
    id_type,
    message_envelope,
    parse_xml,
    system_id,
    tostring,
)
from open_vi.identity import SystemIdentity
from open_vi.platform.port import ServiceStatusSnapshot


def parse_qnh_setting_kpa(xml: str | bytes) -> float | None:
    """Extract VehicleSettings/QNH_Setting (kPa) if present."""
    root = parse_xml(xml)
    text = find_text(root, "QNH_Setting")
    if text is None:
        return None
    return float(text)


def build_system_management_request_status(
    identity: SystemIdentity,
    service: ServiceStatusSnapshot,
    *,
    request_id: UUID,
    processing_state: str = "COMPLETED",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build MA_SystemManagementRequestStatus."""
    data = el(
        "MessageData",
        id_type("RequestID", request_id),
        el("RequestProcessingState", text=processing_state),
        system_id(identity),
        service_id_element(service),
    )
    root = message_envelope(
        "MA_SystemManagementRequestStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_sample_system_management_request(
    identity: SystemIdentity,
    *,
    request_id: UUID,
    qnh_kpa: float = 101.325,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal QNH SystemManagementRequest for unit tests."""
    data = el(
        "MessageData",
        id_type("RequestID", request_id),
        el("RequestState", text="NEW"),
        system_id(identity, tag="ReferenceSystemID"),
        el(
            "RequestType",
            el(
                "VehicleSettings",
                el("QNH_Setting", text=str(qnh_kpa)),
            ),
        ),
    )
    root = message_envelope(
        "MA_SystemManagementRequest",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)
