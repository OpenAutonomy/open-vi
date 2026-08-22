"""Minimal CAL-friendly UCI XML helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID
from xml.etree import ElementTree as ET

from open_vi.codec.ns import NS
from open_vi.identity import SystemIdentity, uuid_to_hex


def q(tag: str) -> str:
    return f"{{{NS}}}{tag}"


def utc_now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def el(tag: str, *children: ET.Element, text: str | None = None) -> ET.Element:
    node = ET.Element(q(tag))
    if text is not None:
        node.text = text
    for child in children:
        node.append(child)
    return node


def local_name(node: ET.Element | str) -> str:
    name = node.tag if isinstance(node, ET.Element) else node
    if name.startswith("{"):
        return name.rsplit("}", 1)[-1]
    if ":" in name:
        return name.split(":", 1)[1]
    return name


def find_all(node: ET.Element, tag: str) -> list[ET.Element]:
    """Find descendants whose local tag name matches ``tag``."""
    return [child for child in node.iter() if local_name(child) == tag]


def find_one(node: ET.Element, tag: str) -> ET.Element | None:
    matches = find_all(node, tag)
    return matches[0] if matches else None


def find_text(node: ET.Element, tag: str) -> str | None:
    child = find_one(node, tag)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def parse_uuid_text(value: str) -> UUID:
    cleaned = value.replace("-", "").strip()
    return UUID(hex=cleaned)


def uuid_under(node: ET.Element, tag: str) -> UUID | None:
    """Return UUID text under ``tag`` (e.g. CommandID/UUID), if present."""
    wrapper = find_one(node, tag)
    if wrapper is None:
        return None
    text = find_text(wrapper, "UUID")
    if not text:
        return None
    return parse_uuid_text(text)


def parse_header_system_id(xml: str | bytes) -> UUID | None:
    """MessageHeader/SystemID, or ``None`` when the header is absent."""
    header = find_one(parse_xml(xml), "MessageHeader")
    if header is None:
        return None
    return uuid_under(header, "SystemID")


def id_type(
    tag: str, value: UUID | str, label: str | None = None
) -> ET.Element:
    if isinstance(value, UUID):
        hex_value = uuid_to_hex(value)
    else:
        hex_value = value.replace("-", "")
    children = [el("UUID", text=hex_value)]
    if label:
        children.append(el("DescriptiveLabel", text=label))
    return el(tag, *children)


def system_id(identity: SystemIdentity, tag: str = "SystemID") -> ET.Element:
    return id_type(tag, identity.uuid, identity.label)


def security_unclassified() -> ET.Element:
    return el(
        "SecurityInformation",
        el("Classification", text="U"),
        el(
            "OwnerProducer",
            el("GovernmentIdentifier", text="USA"),
        ),
    )


def message_header(
    identity: SystemIdentity, *, schema_version: str, mode: str
) -> ET.Element:
    return el(
        "MessageHeader",
        system_id(identity),
        el("Timestamp", text=utc_now()),
        el("SchemaVersion", text=schema_version),
        el("Mode", text=mode),
    )


def message_envelope(
    root_tag: str,
    identity: SystemIdentity,
    message_data: ET.Element,
    *,
    schema_version: str,
    mode: str,
    object_state: str | None = None,
) -> ET.Element:
    root = el(root_tag)
    root.append(security_unclassified())
    root.append(
        message_header(identity, schema_version=schema_version, mode=mode)
    )
    if object_state is not None:
        root.append(el("ObjectState", text=object_state))
    root.append(message_data)
    return root


def tostring(node: ET.Element, *, xml_declaration: bool = True) -> bytes:
    """Serialize with default xmlns and no uci: prefix (CAL-compatible)."""
    ET.register_namespace("", NS)
    for key in list(node.attrib):
        if key == "xmlns" or key.startswith("xmlns:"):
            node.attrib.pop(key, None)
    payload = ET.tostring(node, encoding="utf-8", xml_declaration=False)
    head, sep, rest = payload.partition(b">")
    if sep and b"xmlns=" not in head:
        payload = head + f' xmlns="{NS}"'.encode() + sep + rest
    if xml_declaration:
        return b'<?xml version="1.0" encoding="utf-8"?>\n' + payload
    return payload


def parse_xml(data: str | bytes) -> ET.Element:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return ET.fromstring(data)
