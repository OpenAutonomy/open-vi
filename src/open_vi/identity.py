"""A-GRA system identity (UUID3 under a namespace).

Default identity is open-vi under this project's namespace. Override
with ``VI_SYSTEM_NAME``, ``VI_NAMESPACE_NAME``, and
``VI_NAMESPACE_UUID``.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from uuid import UUID

DEFAULT_SYSTEM_NAME = "open-vi"
DEFAULT_NAMESPACE_NAME = "open-vi"
DEFAULT_NAMESPACE_UUID = uuid.uuid5(
    uuid.NAMESPACE_URL,
    "https://github.com/OpenAutonomy/open-vi",
)
"""Project namespace: ``uuid5`` of the repo URL."""


def namespace_uuid(namespace_uuid_id: str | UUID, namespace_name: str) -> UUID:
    base = UUID(str(namespace_uuid_id))
    return uuid.uuid3(base, namespace_name)


def system_uuid(
    *,
    system_name: str,
    namespace_name: str = DEFAULT_NAMESPACE_NAME,
    namespace_uuid_id: str | UUID = DEFAULT_NAMESPACE_UUID,
) -> UUID:
    """UUID3 of a system name under ``namespace_uuid(...)``.

    Same inputs always yield the same UUID.
    """
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
        namespace_name: str = DEFAULT_NAMESPACE_NAME,
        namespace_uuid_id: str | UUID = DEFAULT_NAMESPACE_UUID,
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
