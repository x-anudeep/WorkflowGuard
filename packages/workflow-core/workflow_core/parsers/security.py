from __future__ import annotations

import json

from lxml import etree


MAX_UPLOAD_BYTES = 5 * 1024 * 1024
ALLOWED_EXTENSIONS = {".bpmn", ".xml", ".json"}


def assert_safe_size(content: bytes) -> None:
    if len(content) == 0:
        raise ValueError("Uploaded workflow file is empty.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ValueError("Uploaded workflow file exceeds the 5 MB limit.")


def safe_json_loads(content: bytes) -> object:
    assert_safe_size(content)
    return json.loads(content.decode("utf-8"))


def safe_xml_parser() -> etree.XMLParser:
    return etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        remove_blank_text=True,
        recover=False,
        huge_tree=False,
    )


def safe_xml_root(content: bytes) -> etree._Element:
    assert_safe_size(content)
    return etree.fromstring(content, parser=safe_xml_parser())
