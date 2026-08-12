"""Harness-compatible system identity (UUID3 over the SUT namespace)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from uuid import UUID

NIL_UUID = UUID("00000000-0000-0000-0000-000000000000")


def namespace_uuid(namespace_uuid_id: str | UUID, namespace_name: str) -> UUID:
    base = UUID(str(namespace_uuid_id))
    return uuid.uuid3(base, namespace_name)


def system_uuid(
    *,
    system_name: str,
    namespace_name: str = "SUT",
    namespace_uuid_id: str | UUID = NIL_UUID,
) -> UUID:
    """Reproduce the official harness platform_system_id scheme."""
    ns = namespace_uuid(namespace_uuid_id, namespace_name)
    return uuid.uuid3(ns, system_name)


def uuid_to_hex(value: UUID) -> str:
    """UCI UniversallyUniqueIdentifierType is xs:hexBinary (no hyphens)."""
    return value.hex


@dataclass(frozen=True)
class SystemIdentity:
    """Platform identity used in UCI MessageHeader / ID fields."""

    uuid: UUID
    label: str
    name: str
    namespace_name: str

    @property
    def hex(self) -> str:
        return uuid_to_hex(self.uuid)

    @classmethod
    def named(
        cls,
        system_name: str,
        label: str | None = None,
        *,
        namespace_name: str = "SUT",
        namespace_uuid_id: str | UUID = NIL_UUID,
    ) -> SystemIdentity:
        return cls(
            uuid=system_uuid(
                system_name=system_name,
                namespace_name=namespace_name,
                namespace_uuid_id=namespace_uuid_id,
            ),
            label=label or system_name,
            name=system_name,
            namespace_name=namespace_name,
        )
