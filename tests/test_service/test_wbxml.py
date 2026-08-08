"""WBXML 1.3 engine tests — real binary round-trips, not JSON fakery."""
from __future__ import annotations

import pytest

from app.service.activesync import Wbxml
from app.service.activesync.Wbxml import (
    WbxmlDecoder,
    WbxmlEncoder,
    WbxmlError,
    encode_mbint,
    group,
    leaf,
    opaque_node as opaque,
)


def _decode(data: bytes) -> list:
    return WbxmlDecoder.decode(data)


def test_header_bytes_are_spec_conformant():
    root = group("AirSync", "Sync", [leaf("AirSync", "Status", 1)])
    data = WbxmlEncoder.encode(root)
    assert data[0] == 0x03                 # version 1.3
    assert data[1:3] == b"\x01\x6a"        # public id unknown, charset utf-8
    assert data[3] == 0x00                 # empty string table


def test_roundtrip_text_and_pages():
    root = group("FolderHierarchy", "FolderSync", [
        leaf("FolderHierarchy", "SyncKey", "k-1"),
        leaf("AirSync", "Status", 1),
        group("FolderHierarchy", "Changes", [
            leaf("FolderHierarchy", "Count", 2),
            group("FolderHierarchy", "Add", [
                group("FolderHierarchy", "Folder", [
                    leaf("FolderHierarchy", "ServerId", "abc=="),
                    leaf("FolderHierarchy", "DisplayName", "Inbox"),
                ]),
            ]),
        ]),
    ])
    tree = _decode(WbxmlEncoder.encode(root))
    assert [n for n, _ in tree] == ["FolderSync"]
    (name, payload), = tree
    assert _text(payload, "SyncKey") == "k-1"
    assert _text(payload, "Status") == "1"
    changes = _child(payload, "Changes")
    assert _text(changes, "Count") == "2"


def test_switch_page_between_folders():
    root = group("AirSync", "Sync", [
        leaf("AirSync", "Status", 1),
        leaf("AirSync", "SyncKey", "k9"),
        group("AirSync", "Commands", [
            group("AirSync", "Add", [
                leaf("Email", "Subject", "hello"),
                group("AirSyncBase", "Body", [leaf("AirSyncBase", "Type", 1)]),
            ]),
        ]),
    ])
    tree = _decode(WbxmlEncoder.encode(root))
    add = _child(_child(tree[0][1], "Commands"), "Add")
    assert _text(add, "Subject") == "hello"
    assert _text(_child(add, "Body"), "Type") == "1"


def test_opaque_bytes_roundtrip_preserved():
    raw = b"From: a@b\r\n\r\nBINARY\x00\xffDATA"
    root = group("AirSyncBase", "Body", [opaque("AirSyncBase", "Data", raw)])
    tree = _decode(WbxmlEncoder.encode(root))
    inner = tree[0][1][0][1]  # [('$opaque', raw)]
    assert inner[0] == ("$opaque", raw)


def test_mbint_encoding():
    for value in (0, 1, 0x7F, 0x80, 0x3FFF, 0x4000, 2**21 - 1):
        encoded = encode_mbint(value)
        decoded, pos = Wbxml.decode_mbint(encoded, 0)
        assert decoded == value
        assert pos == len(encoded)


def test_unknown_tag_raises():
    root = group("AirSyncBase", "Body", [leaf("AirSync", "Nope", "1")])
    with pytest.raises(WbxmlError):
        WbxmlEncoder.encode(root)


def test_unknown_page_raises():
    from app.service.activesync.Wbxml import WbxmlTag
    with pytest.raises(WbxmlError):
        WbxmlEncoder.encode(WbxmlTag("NotAPage", "Foo"))


def test_truncated_stream_raises():
    root = group("AirSync", "Sync", [leaf("AirSync", "Status", "1")])
    data = WbxmlEncoder.encode(root)
    with pytest.raises(WbxmlError):
        _decode(data[:-1])


def test_wrong_version_raises():
    with pytest.raises(WbxmlError):
        _decode(b"\x02\x01\x6a\x00")


# helpers --------------------------------------------------------------- #

def _child(payload, name):
    """Find the child node named `name` inside a decoded payload list."""
    for node, p in payload or []:
        if node == name:
            return p
    raise AssertionError(f"child {name} not found in {payload}")


def _text(payload, name: str) -> str | None:
    for node, p in (payload or []):
        if node == name:
            for inner, value in (p or []):
                if inner == "$text":
                    return value
            return None
    return None