"""Parse/build MA_TaskCommand status and MA_Task (Flight suggest)."""

from __future__ import annotations

from dataclasses import dataclass
from uuid import UUID

from open_vi.codec.ns import SCHEMA_VERSION
from open_vi.codec.xmlutil import (
    el,
    find_all,
    find_one,
    find_text,
    id_type,
    local_name,
    message_envelope,
    parse_uuid_text,
    parse_xml,
    system_id,
    tostring,
    uuid_under,
)
from open_vi.identity import SystemIdentity


@dataclass(frozen=True)
class TaskCommandRequest:
    """Parsed MA_TaskCommand Capability instance."""

    command_id: UUID
    task_id: UUID
    capability_id: UUID | None = None
    command_state: str = "NEW"


@dataclass(frozen=True)
class InboundTask:
    """Parsed inbound MA_Task (TaskID + object state)."""

    task_id: UUID
    object_state: str | None = None


def parse_ma_task(xml: str | bytes) -> InboundTask | None:
    """Extract TaskID from MA_Task; ``None`` if TaskID is missing."""
    root = parse_xml(xml)
    if local_name(root) != "MA_Task":
        raise ValueError(f"expected MA_Task, got {local_name(root)}")
    data = find_one(root, "MessageData")
    if data is None:
        return None
    task_id = uuid_under(data, "TaskID")
    if task_id is None:
        return None
    return InboundTask(
        task_id=task_id,
        object_state=find_text(root, "ObjectState"),
    )


def parse_task_commands(xml: str | bytes) -> list[TaskCommandRequest]:
    """Extract Capability command instances from MA_TaskCommand."""
    root = parse_xml(xml)
    if local_name(root) != "MA_TaskCommand":
        raise ValueError(f"expected MA_TaskCommand, got {local_name(root)}")
    data = find_one(root, "MessageData")
    if data is None:
        raise ValueError("MA_TaskCommand missing MessageData")
    requests: list[TaskCommandRequest] = []
    for command in find_all(data, "Command"):
        cap = None
        for child in list(command):
            if local_name(child) == "Capability":
                cap = child
                break
        if cap is None:
            continue
        command_id_text = None
        cmd_id_node = find_one(cap, "CommandID")
        if cmd_id_node is not None:
            command_id_text = find_text(cmd_id_node, "UUID")
        if not command_id_text:
            raise ValueError("MA_TaskCommand missing CommandID/UUID")
        task_id_text = None
        task_node = find_one(cap, "TaskID")
        if task_node is not None:
            task_id_text = find_text(task_node, "UUID")
        if not task_id_text:
            raise ValueError("MA_TaskCommand missing TaskID/UUID")
        cap_text = None
        cap_node = find_one(cap, "CapabilityID")
        if cap_node is not None:
            cap_text = find_text(cap_node, "UUID")
        requests.append(
            TaskCommandRequest(
                command_id=parse_uuid_text(command_id_text),
                task_id=parse_uuid_text(task_id_text),
                capability_id=(parse_uuid_text(cap_text) if cap_text else None),
                command_state=find_text(cap, "CommandState") or "NEW",
            )
        )
    return requests


def build_task_command_status(
    identity: SystemIdentity,
    *,
    command_id: UUID,
    processing_state: str = "ACCEPTED",
    reason: str | None = None,
    reason_description: str | None = None,
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build MA_TaskCommandStatus for an accept/reject decision."""
    children = [
        id_type("CommandID", command_id),
        el("CommandProcessingState", text=processing_state),
    ]
    if reason:
        reason_kids = [el("Reason", text=reason)]
        if reason_description:
            reason_kids.append(el("Description", text=reason_description))
        children.append(el("CommandProcessingStateReason", *reason_kids))
    data = el("MessageData", *children)
    root = message_envelope(
        "MA_TaskCommandStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_task_status(
    identity: SystemIdentity,
    *,
    task_id: UUID,
    execution_state: str = "EXECUTING",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build TaskStatus for an accepted or canceled TaskCommand."""
    data = el(
        "MessageData",
        system_id(identity, "ExecutingSystemID"),
        el("ExecutionState", text=execution_state),
        id_type("TaskID", task_id, "flight-task"),
    )
    root = message_envelope(
        "TaskStatus",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)


def build_ma_task(
    identity: SystemIdentity,
    *,
    task_id: UUID,
    plurality: str = "SINGLE_ENTITY",
    object_state: str = "NEW",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Build MA_Task suggesting a Flight task (reject / tasking path)."""
    data = el(
        "MessageData",
        id_type("TaskID", task_id, "flight-task"),
        el(
            "TaskType",
            el("Flight", el("CapabilityType", text="MUST_FLY")),
        ),
        el("TaskPlurality", text=plurality),
    )
    root = message_envelope(
        "MA_Task",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
        object_state=object_state,
    )
    return tostring(root)


def build_sample_task_command(
    identity: SystemIdentity,
    *,
    command_id: UUID,
    task_id: UUID,
    capability_id: UUID,
    command_state: str = "NEW",
    schema_version: str = SCHEMA_VERSION,
    mode: str = "SIMULATION",
) -> bytes:
    """Minimal MA_TaskCommand for unit tests."""
    capability = el(
        "Capability",
        id_type("CommandID", command_id),
        el("CommandState", text=command_state),
        id_type("CapabilityID", capability_id, "flight-capability"),
        el(
            "Ranking",
            el(
                "Rank",
                el("Priority", text="0"),
                el("PrecedenceWithinPriority", text="0"),
            ),
        ),
        id_type("TaskID", task_id),
    )
    data = el("MessageData", el("Command", capability))
    root = message_envelope(
        "MA_TaskCommand",
        identity,
        data,
        schema_version=schema_version,
        mode=mode,
    )
    return tostring(root)
