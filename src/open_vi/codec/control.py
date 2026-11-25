"""Parse/build MA_ControlRequest, Status, and MA_ControlAssignment."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID
from xml.etree import ElementTree as ET

from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.xmlutil import (
    el,
    find_one,
    find_text,
    id_type,
    local_name,
    message_envelope,
    parse_xml,
    tostring,
    uuid_under,
)
from open_vi.identity import SystemIdentity

_ACQUIRE_TYPES = frozenset({"ACQUIRE", "STEAL", "ASSIGN_STEAL"})


@dataclass(frozen=True)
class ControlRequest:
    """Parsed MA_ControlRequest (acquire / release / steal)."""

    request_id: UUID
    request_type: str  # ACQUIRE | RELEASE | STEAL | ASSIGN_STEAL
    request_state: str = "NEW"
    control_type: str = "CAPABILITY_PRIMARY"
    control_choice: str = "GrantedControlType"
    controller_system_id: UUID | None = None
    controller_service_id: UUID | None = None
    controllee_system_id: UUID | None = None
    capability_id: UUID | None = None

    @property
    def is_acquire(self) -> bool:
        return self.request_type.upper() in _ACQUIRE_TYPES

    @property
    def is_release(self) -> bool:
        return self.request_type.upper() == "RELEASE"


def parse_control_request(xml: str | bytes) -> ControlRequest | None:
    """Extract one ControlRequest; None if RequestID is missing."""
    root = parse_xml(xml)
    if local_name(root) != "MA_ControlRequest":
        raise ValueError(f"expected MA_ControlRequest, got {local_name(root)}")
    data = find_one(root, "MessageData")
    if data is None:
        raise ValueError("MA_ControlRequest missing MessageData")
    request_id = uuid_under(data, "RequestID")
    if request_id is None:
        return None
    request_type = (find_text(data, "RequestType") or "ACQUIRE").upper()
    request_state = find_text(data, "RequestState") or "NEW"
    choice_el = find_one(data, "ControlChoiceType")
    control_choice = "GrantedControlType"
    control_type = "CAPABILITY_PRIMARY"
    if choice_el is not None:
        granted = find_text(choice_el, "GrantedControlType")
        permitted = find_text(choice_el, "PermittedControlType")
        if granted:
            control_choice = "GrantedControlType"
            control_type = granted
        elif permitted:
            control_choice = "PermittedControlType"
            control_type = permitted
    controller = find_one(data, "Controller")
    controller_system = None
    controller_service = None
    if controller is not None:
        controller_system = uuid_under(controller, "SystemID")
        controller_service = uuid_under(controller, "ServiceID")
    controllee = find_one(data, "Controllee")
    controllee_system = None
    capability_id = None
    if controllee is not None:
        controllee_system = uuid_under(controllee, "SystemID")
        capability_id = uuid_under(controllee, "CapabilityID")
    return ControlRequest(
        request_id=request_id,
        request_type=request_type,
        request_state=request_state,
        control_type=control_type,
        control_choice=control_choice,
        controller_system_id=controller_system,
        controller_service_id=controller_service,
        controllee_system_id=controllee_system,
        capability_id=capability_id,
    )


def _assignment_element(
    *,
    control_type: str,
    control_choice: str,
    controller_system_id: UUID,
    controller_service_id: UUID | None,
    controllee_system_id: UUID,
    capability_id: UUID | None,
) -> ET.Element:
    choice = el("ControlChoiceType", el(control_choice, text=control_type))
    controller_kids = [id_type("SystemID", controller_system_id)]
    if controller_service_id is not None:
        controller_kids.append(id_type("ServiceID", controller_service_id))
    controllee_kids = [id_type("SystemID", controllee_system_id)]
    if capability_id is not None:
        controllee_kids.append(
            id_type("CapabilityID", capability_id, "flight-capability")
        )
    return el(
        "ControlAssignment",
        choice,
        el("Controller", *controller_kids),
        el("Controllee", *controllee_kids),
    )


# States that a reason explains. A reason element annotates the state
# beside it, so each is emitted only when its own state is one of
# these -- not whenever the caller supplies a reason.
_UNSUCCESSFUL_STATES = frozenset({"REJECTED", "CANCELED", "FAILED"})


def build_control_request_status(
    identity: SystemIdentity,
    *,
    request_id: UUID,
    processing_state: str,
    approval_state: str,
    reason: str | None = None,
    reason_description: str | None = None,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build MA_ControlRequestStatus (request + approval states).

    ``MA_ControlRequestStatusMDT`` extends ``RequestStatusBaseType``,
    so there are two optional reason elements: the inherited
    ``RequestProcessingStateReason`` for the request, and
    ``ApprovalRequestProcessingStateReason`` for the approval
    decision. Tables 1-12 and 1-13 require the approval one on a
    rejected or ``CANCELED`` status, and both being ``[0..1]`` means
    neither the XSD nor Table 1-38 notices if only the other is sent.

    *reason* annotates whichever of the two states is unsuccessful.
    ``_reject`` and ``unpair_assignment`` set both, so both carry it.
    """
    children = [
        id_type("RequestID", request_id),
        el("RequestProcessingState", text=processing_state),
    ]

    def _reason_element(name: str) -> ET.Element:
        reason_kids = [el("Reason", text=reason)]
        if reason_description:
            reason_kids.append(el("Description", text=reason_description))
        return el(name, *reason_kids)

    if reason and processing_state.upper() in _UNSUCCESSFUL_STATES:
        children.append(_reason_element("RequestProcessingStateReason"))
    children.append(el("ApprovalRequestProcessingState", text=approval_state))
    if reason and approval_state.upper() in _UNSUCCESSFUL_STATES:
        # Declared after ApprovalRequestProcessingState; the MDT is an
        # xs:sequence, so position matters.
        children.append(_reason_element("ApprovalRequestProcessingStateReason"))
    data = el("MessageData", *children)
    root = message_envelope(
        "MA_ControlRequestStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_control_assignment(
    identity: SystemIdentity,
    *,
    control_type: str,
    control_choice: str,
    controller_system_id: UUID,
    controller_service_id: UUID | None,
    controllee_system_id: UUID,
    capability_id: UUID | None,
    object_state: str = "NEW",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build MA_ControlAssignment (granted or removed)."""
    assignment = _assignment_element(
        control_type=control_type,
        control_choice=control_choice,
        controller_system_id=controller_system_id,
        controller_service_id=controller_service_id,
        controllee_system_id=controllee_system_id,
        capability_id=capability_id,
    )
    data = el("MessageData", assignment)
    root = message_envelope(
        "MA_ControlAssignment",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
        object_state=object_state,
    )
    return tostring(root)


def build_sample_control_request(
    identity: SystemIdentity,
    *,
    request_id: UUID,
    request_type: str = "ACQUIRE",
    controller_system_id: UUID | None = None,
    controller_service_id: UUID | None = None,
    capability_id: UUID | None = None,
    control_type: str = "CAPABILITY_PRIMARY",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal MA_ControlRequest for unit tests."""
    controller = controller_system_id or identity.uuid
    assignment = _assignment_element(
        control_type=control_type,
        control_choice="GrantedControlType",
        controller_system_id=controller,
        controller_service_id=controller_service_id,
        controllee_system_id=identity.uuid,
        capability_id=capability_id,
    )
    data = el(
        "MessageData",
        id_type("RequestID", request_id),
        el("RequestState", text="NEW"),
        assignment,
        el("RequestType", text=request_type),
    )
    root = message_envelope(
        "MA_ControlRequest",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)
