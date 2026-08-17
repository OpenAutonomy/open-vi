"""Builders for ServiceStatus, SubsystemStatus, and MA_Fault."""

from __future__ import annotations

from uuid import UUID
from xml.etree import ElementTree as ET

from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.xmlutil import (
    el,
    id_type,
    message_envelope,
    parse_xml,
    tostring,
    uuid_under,
)
from open_vi.domain import (
    FaultSnapshot,
    ServiceStatusSnapshot,
    SubsystemStatusSnapshot,
)
from open_vi.identity import SystemIdentity, uuid_to_hex


def service_id_element(status: ServiceStatusSnapshot) -> ET.Element:
    children = [
        el("UUID", text=uuid_to_hex(status.service_id)),
        el("DescriptiveLabel", text=status.service_label),
    ]
    if status.service_version:
        children.append(el("ServiceVersion", text=status.service_version))
    return el("ServiceID", *children)


def _service_status_body(status: ServiceStatusSnapshot) -> list[ET.Element]:
    return [
        service_id_element(status),
        el("TimeUp", text=status.time_up),
        el("ServiceState", text=status.service_state),
    ]


def build_service_status(
    identity: SystemIdentity,
    status: ServiceStatusSnapshot,
    *,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build ServiceStatus (VI heartbeat)."""
    data = el("MessageData", *_service_status_body(status))
    root = message_envelope(
        "ServiceStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_service_status_data_request_status(
    identity: SystemIdentity,
    status: ServiceStatusSnapshot,
    *,
    request_id: UUID,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build ServiceStatusDataRequestStatus with embedded ServiceStatusData."""
    data = el(
        "MessageData",
        id_type("RequestID", request_id),
        el("RequestProcessingState", text="COMPLETED"),
        el("ServiceStatusData", *_service_status_body(status)),
    )
    root = message_envelope(
        "ServiceStatusDataRequestStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def _subsystem_status_body(
    status: SubsystemStatusSnapshot,
) -> list[ET.Element]:
    about = el(
        "About",
        el("Model", text=status.model),
        el("SoftwareVersion", text=status.software_version),
    )
    return [
        id_type("SubsystemID", status.subsystem_id, status.subsystem_label),
        el("SubsystemState", text=status.subsystem_state),
        about,
    ]


def build_subsystem_status(
    identity: SystemIdentity,
    status: SubsystemStatusSnapshot,
    *,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build SubsystemStatus."""
    data = el("MessageData", *_subsystem_status_body(status))
    root = message_envelope(
        "SubsystemStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_subsystem_status_data_request_status(
    identity: SystemIdentity,
    status: SubsystemStatusSnapshot,
    *,
    request_id: UUID,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build SubsystemStatusDataRequestStatus (OPT path)."""
    data = el(
        "MessageData",
        id_type("RequestID", request_id),
        el("RequestProcessingState", text="COMPLETED"),
        el("SubsystemStatusData", *_subsystem_status_body(status)),
    )
    root = message_envelope(
        "SubsystemStatusDataRequestStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_ma_fault(
    identity: SystemIdentity,
    faults: tuple[FaultSnapshot, ...],
    *,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
    object_state: str = "NEW",
) -> bytes:
    """Build MA_Fault with one or more FaultInformation entries."""
    infos: list[ET.Element] = []
    for fault in faults:
        infos.append(
            el(
                "FaultInformation",
                id_type("FaultID", fault.fault_id),
                el("FaultState", text=fault.fault_state),
                el("FaultCode", text=fault.fault_code),
                el("FaultDescription", text=fault.fault_description),
            )
        )
    if not infos:
        raise ValueError("MA_Fault requires at least one FaultInformation")
    data = el("MessageData", *infos)
    root = message_envelope(
        "MA_Fault",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
        object_state=object_state,
    )
    return tostring(root)


def parse_request_id(xml: str | bytes) -> UUID | None:
    """Extract RequestID/UUID from a *DataRequest message."""
    root = parse_xml(xml)
    return uuid_under(root, "RequestID")


def parse_service_id(xml: str | bytes) -> UUID | None:
    """Extract ServiceID/UUID from a ServiceStatus message."""
    root = parse_xml(xml)
    return uuid_under(root, "ServiceID")


def build_sample_service_status(
    identity: SystemIdentity,
    *,
    service_id: UUID,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Inbound-style ServiceStatus for unit tests (foreign service id)."""
    return build_service_status(
        identity,
        ServiceStatusSnapshot(
            service_id=service_id,
            service_label="harness-ma",
            time_up="PT1S",
            service_state="NORMAL",
        ),
        schema_version=schema_version,
        mode=mode,
    )


def build_sample_service_status_data_request(
    identity: SystemIdentity,
    *,
    request_id: UUID,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal ServiceStatusDataRequest for unit tests."""
    data = el(
        "MessageData",
        id_type("RequestID", request_id),
        el("RequestState", text="NEW"),
    )
    root = message_envelope(
        "ServiceStatusDataRequest",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_sample_subsystem_status_data_request(
    identity: SystemIdentity,
    *,
    request_id: UUID,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal SubsystemStatusDataRequest for unit tests."""
    data = el(
        "MessageData",
        id_type("RequestID", request_id),
        el("RequestState", text="NEW"),
    )
    root = message_envelope(
        "SubsystemStatusDataRequest",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)
