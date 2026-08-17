"""Builders for MA_SystemNotification (route ingest, failsafe, etc.)."""

from __future__ import annotations

from uuid import UUID, uuid4
from xml.etree import ElementTree as ET

from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.status import service_id_element
from open_vi.codec.xmlutil import (
    el,
    id_type,
    message_envelope,
    parse_xml,
    system_id,
    tostring,
    utc_now,
    uuid_under,
)
from open_vi.domain import ServiceStatusSnapshot
from open_vi.identity import SystemIdentity


def parse_response_id(xml: str | bytes) -> UUID | None:
    """Extract ResponseID/UUID from MA_Response."""
    root = parse_xml(xml)
    return uuid_under(root, "ResponseID")


def build_system_notification(
    identity: SystemIdentity,
    *,
    associated_message_type: str,
    associated_id: UUID | None,
    service: ServiceStatusSnapshot,
    notification_state: str = "CONFIRMED",
    severity: str = "INFORMATIONAL",
    perspective: str = "SOURCE",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build MA_SystemNotification with an AssociatedMessage."""
    source_children: list[ET.Element] = [
        system_id(identity),
        service_id_element(service),
    ]
    associated = el(
        "AssociatedMessage",
        el("MessageType", text=associated_message_type),
    )
    if associated_id is not None:
        associated.append(id_type("AssociatedID", associated_id))
    data = el(
        "MessageData",
        id_type("NotificationID", uuid4()),
        el("NotificationState", text=notification_state),
        el("Timestamp", text=utc_now()),
        el("Source", *source_children),
        el("Severity", text=severity),
        el("SystemSubjectIDs", system_id(identity)),
        el("SystemPerspective", text=perspective),
        associated,
    )
    root = message_envelope(
        "MA_SystemNotification",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_sample_ma_response(
    identity: SystemIdentity,
    *,
    response_id: UUID,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal MA_Response for failsafe unit tests (not schema-complete)."""
    data = el(
        "MessageData",
        id_type("ResponseID", response_id),
        el("ResponseType", text="DO_NOTHING"),
        el(
            "Option",
            el("OptionIndex", text="0"),
            el("ContinueEvaluation", text="false"),
            el("Enabled", text="true"),
        ),
    )
    root = message_envelope(
        "MA_Response",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
        object_state="NEW",
    )
    return tostring(root)
