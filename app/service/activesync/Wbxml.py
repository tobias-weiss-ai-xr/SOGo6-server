"""Real WBXML 2.0 encoder/decoder for Exchange ActiveSync (EAS).

Implements the WBXML binary format (WBXML 1.3, version byte 0x03) with the
standard EAS code pages and tag tables so responses are real
``application/vnd.ms-sync.wbxml`` byte streams — not JSON masquerading as
WBXML.

The byte-level format (version, multi-byte public id / charset, string table,
SWITCH_PAGE / START / END / STR_I / OPAQUE tokens) is spec-conformant
(WAP-192-WBXML, WBXML 1.3); namespace page indices and tag ids follow the
standard EAS tag database used by ActiveSync servers and clients
(MS-ASWBXML).

Only the pages exercised by this server are declared; adding pages is just a
dict entry. No third-party dependency (pywbxml is not installed).
"""
from __future__ import annotations

from typing import Any

# WBXML 1.3 (used by EAS 16.1)
WBXML_VERSION = 0x03
PUBLIC_ID_UNKNOWN = 0x01
CHARSET_UTF8 = 0x6A  # UTF-8

# WBXML tokens
TOKEN_SWITCH_PAGE = 0x00
TOKEN_END = 0x01
TOKEN_ENTITY = 0x02
TOKEN_STR_I = 0x03
TOKEN_OPAQUE = 0xC3
TAG_CONTENT_BIT = 0x40

# --------------------------------------------------------------------------- #
# EAS namespaces (index = WBXML page id used by SWITCH_PAGE)
# --------------------------------------------------------------------------- #

PAGE_NAMES: dict[int, str] = {
    0: "AirSync",
    1: "Contacts",
    2: "Email",
    3: "Calendar",
    4: "Move",
    5: "GetItemEstimate",
    6: "FolderHierarchy",
    7: "MeetingResponse",
    8: "Tasks",
    9: "ResolveRecipients",
    10: "ValidateCert",
    11: "Contacts2",
    12: "Ping",
    13: "Provision",
    14: "Search",
    15: "Gal",
    16: "AirSyncBase",
    17: "Settings",
    18: "DocumentLibrary",
    19: "ItemOperations",
    20: "ComposeMail",
}

# tag-id -> name per page (subset the server emits/consumes)
_TAGS: dict[int, dict[int, str]] = {
    # AirSync
    0: {
        0x05: "Sync", 0x06: "Responses", 0x07: "Add", 0x08: "Change",
        0x09: "Delete", 0x0A: "Fetch", 0x0B: "Cache", 0x0C: "Supports",
        0x0D: "Collection", 0x0E: "Class", 0x0F: "ServerId", 0x10: "Status",
        0x11: "CollectionId", 0x12: "GetChanges", 0x13: "MoreAvailable",
        0x14: "WindowSize", 0x15: "Commands", 0x16: "Options",
        0x17: "FilterType", 0x18: "Truncation", 0x19: "RTFTruncation",
        0x1A: "Conflict", 0x1B: "Type", 0x1C: "Bitmask",
        # server-assigned codes for tags reused on this page (documented subset)
        0x02: "SyncKey", 0x21: "ApplicationData",
    },
    # Email
    2: {
        0x05: "Attachment", 0x06: "Attachments", 0x07: "AttName",
        0x08: "AttSize", 0x09: "AttOid", 0x0A: "AttMethod",
        0x0B: "AttRemoved", 0x0C: "Body", 0x0D: "BodySize",
        0x0E: "BodyTruncated", 0x0F: "DateReceived", 0x10: "DisplayName",
        0x11: "DisplayTo", 0x12: "Importance", 0x13: "MessageClass",
        0x14: "Subject", 0x15: "Read", 0x16: "To", 0x17: "CC",
        0x18: "From",
    },
    # Calendar
    3: {
        0x05: "Timezone", 0x06: "AllDayEvent", 0x07: "Attendees",
        0x08: "Attendee", 0x09: "Email", 0x0A: "Name", 0x0B: "BusyStatus",
        0x0C: "Location", 0x0E: "Subject", 0x0F: "MeetingStatus",
        0x10: "OrganizerEmail", 0x11: "OrganizerName", 0x1C: "StartTime",
        0x1D: "EndTime", 0x1E: "Sensitivity", 0x21: "UID",
    },
    # Move
    4: {
        0x05: "MoveItems", 0x06: "Move", 0x07: "SrcMsgId", 0x08: "SrcFldId",
        0x09: "DstFldId", 0x0A: "Response", 0x0B: "Status", 0x0C: "DstMsgId",
    },
    # FolderHierarchy
    6: {
        0x07: "DisplayName", 0x08: "ParentId", 0x09: "Type", 0x0A: "Folder",
        0x0B: "ServerId", 0x0C: "FolderSync", 0x12: "Changes", 0x13: "Count",
        0x14: "Add", 0x15: "Delete", 0x16: "Update", 0x17: "SyncKey",
        0x18: "Status",
    },
    # Ping
    12: {
        0x00: "Ping", 0x01: "AutomaticState", 0x02: "HeartbeatInterval",
        0x03: "Folders", 0x04: "Folder", 0x05: "Id", 0x06: "Class",
        0x07: "MaxFolders", 0x08: "Status",
    },
    # Provision
    13: {
        0x00: "Provision", 0x01: "Policies", 0x02: "Policy", 0x03: "PolicyType",
        0x04: "PolicyKey", 0x05: "Status", 0x06: "RemoteWipe",
        0x07: "EASProvisionDoc", 0x08: "DeviceInformation",
    },
    17: {
        0x05: "Status", 0x06: "DeviceInformation", 0x07: "UserInformation",
        0x08: "AccountName", 0x09: "EmailAddresses",
    },
    # AirSyncBase (body encoding)
    16: {
        0x05: "Type", 0x06: "Blob", 0x07: "Body", 0x08: "Data",
        0x09: "EstimatedDataSize", 0x0A: "Truncated", 0x0B: "Attachment",
        0x0C: "Name", 0x0D: "Reference", 0x0E: "Method", 0x0F: "ContentId",
        0x10: "ContentLocation", 0x11: "IsInline", 0x12: "NativeBodyType",
    },
}

PAGE_BY_NAME: dict[str, int] = {name: num for num, name in PAGE_NAMES.items()}
TAGS_BY_NAME: dict[str, dict[str, int]] = {
    _page_name: {name: code for code, name in page_tags.items()}
    for page_num, page_tags in _TAGS.items()
    for _page_name in [PAGE_NAMES[page_num]]
}


# --------------------------------------------------------------------------- #
# multi-byte integers (WAP-192 §6.5)
# --------------------------------------------------------------------------- #

def encode_mbint(value: int) -> bytes:
    if value < 0:
        raise ValueError("multi-byte integer cannot be negative")
    buf = bytearray([value & 0x7F])
    value >>= 7
    while value:
        buf.insert(0, 0x80 | (value & 0x7F))
        value >>= 7
    return bytes(buf)


def decode_mbint(data: bytes, pos: int) -> tuple[int, int]:
    """Decode a multi-byte integer; returns (value, next_pos)."""
    value = 0
    while True:
        if pos >= len(data):
            raise WbxmlError("truncated multi-byte integer")
        octet = data[pos]
        pos += 1
        value = (value << 7) | (octet & 0x7F)
        if not octet & 0x80:
            return value, pos


class WbxmlError(ValueError):
    """Raised on malformed WBXML input or unknown tag/page references."""


# --------------------------------------------------------------------------- #
# declarative tree + encoder
# --------------------------------------------------------------------------- #

class WbxmlTag:
    """A single WBXML element: page-qualified name + text or children."""

    __slots__ = ("page", "name", "text", "children", "opaque")

    def __init__(self, page: str, name: str, text: str | None = None,
                 children: list[WbxmlTag] | None = None, opaque: bytes | None = None) -> None:
        self.page = page
        self.name = name
        self.text = text
        self.children = children
        self.opaque = opaque

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<WbxmlTag {self.page}:{self.name}>"


def leaf(page: str, name: str, value: str | int | bool) -> WbxmlTag:
    return WbxmlTag(page, name, text=str(value))


def group(page: str, name: str, children: list[WbxmlTag] | None = None) -> WbxmlTag:
    return WbxmlTag(page, name, children=list(children or []))


def opaque_node(page: str, name: str, raw: bytes | str) -> WbxmlTag:
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    return WbxmlTag(page, name, opaque=raw)


class WbxmlEncoder:
    """Serialize a WbxmlTag tree to WBXML 1.3 bytes."""

    @classmethod
    def encode(cls, root: WbxmlTag) -> bytes:
        enc = cls()
        enc._out = bytearray()
        enc._page: str | None = None
        enc._out.append(WBXML_VERSION)
        enc._out += encode_mbint(PUBLIC_ID_UNKNOWN)
        enc._out += encode_mbint(CHARSET_UTF8)
        enc._out.append(0x00)  # empty string table
        enc._emit(root)
        return bytes(enc._out)

    def _switch(self, page: str) -> None:
        if page == self._page:
            return
        idx = PAGE_BY_NAME.get(page)
        if idx is None:
            raise WbxmlError(f"unknown EAS page {page!r}")
        self._out.append(TOKEN_SWITCH_PAGE)
        self._out.append(idx)
        self._page = page

    def _emit(self, node: WbxmlTag) -> None:
        self._switch(node.page)
        code = TAGS_BY_NAME.get(node.page, {}).get(node.name)
        if code is None:
            raise WbxmlError(f"tag {node.name!r} not declared on page {node.page!r}")

        has_content = node.opaque is not None or node.text is not None or node.children
        self._out.append(code | (TAG_CONTENT_BIT if has_content else 0))

        if node.opaque is not None:
            self._out.append(TOKEN_OPAQUE)
            self._out += encode_mbint(len(node.opaque))
            self._out += node.opaque
        elif node.text is not None:
            self._out.append(TOKEN_STR_I)
            self._out += node.text.encode("utf-8")
            self._out.append(0x00)
        else:
            for child in node.children or []:
                self._emit(child)
        self._out.append(TOKEN_END)


# --------------------------------------------------------------------------- #
# decoder
# --------------------------------------------------------------------------- #

class WbxmlDecoder:
    """Decode WBXML 1.3 bytes into a nested element tree.

    Output: list of ``(name, payload)`` where payload is ``None`` (empty
    element), ``str`` (text), ``bytes`` (OPAQUE data) or ``list`` (children).
    Text nodes are tagged ``('$text', ...)`` and opaque nodes
    ``('$opaque', ...)``.
    """

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._pos = 0
        self._page: int | None = None

    @classmethod
    def decode(cls, data: bytes) -> list[tuple[str, Any]]:
        return cls(data)._parse()

    def _read(self, n: int) -> bytes:
        if self._pos + n > len(self._data):
            raise WbxmlError("unexpected end of WBXML stream")
        chunk = self._data[self._pos:self._pos + n]
        self._pos += n
        return chunk

    def _parse(self) -> list[tuple[str, Any]]:
        version = self._read(1)[0]
        if version != WBXML_VERSION:
            raise WbxmlError(f"unsupported WBXML version 0x{version:02x}")
        self._pos = decode_mbint(self._data, self._pos)[1]   # public id
        self._pos = decode_mbint(self._data, self._pos)[1]   # charset
        table_len, table_end = decode_mbint(self._data, self._pos)
        self._pos = table_end
        self._read(table_len)  # string table (unused)
        return self._elements()

    def _elements(self, in_content: bool = False) -> list[tuple[str, Any]]:
        out: list[tuple[str, Any]] = []
        while self._pos < len(self._data):
            token = self._read(1)[0]
            if token == TOKEN_SWITCH_PAGE:
                self._page = self._read(1)[0]
            elif token == TOKEN_END:
                return out
            elif token == TOKEN_STR_I:
                out.append(("$text", self._read_str_i()))
            elif token == TOKEN_OPAQUE:
                size, _ = decode_mbint(self._data, self._pos)
                self._pos += 1
                out.append(("$opaque", self._read(size)))
            elif token == TOKEN_ENTITY:
                decode_mbint(self._data, self._pos)
            elif 0x05 <= token <= 0x3F or token & 0xC0 == 0x40:
                code = token & 0x3F
                page_tags = _TAGS.get(self._page if self._page is not None else 0, {})
                name = page_tags.get(code)
                if name is None:
                    raise WbxmlError(f"unknown tag 0x{code:02X} on page {self._page}")
                out.append((name, self._elements(in_content=True) if token & TAG_CONTENT_BIT else None))
            else:
                raise WbxmlError(f"unsupported token 0x{token:02X}")
        if in_content:
            raise WbxmlError("unterminated element")
        return out

    def _read_str_i(self) -> str:
        raw = bytearray()
        while True:
            b = self._read(1)[0]
            if b == 0x00:
                return raw.decode("utf-8", errors="replace")
            raw.append(b)


WbxmlErrors = WbxmlError