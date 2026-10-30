"""Minimal protobuf decoder for the v5 hashes.search response. No protobuf dependency.

The response arrives as application/x-protobuf when alt=json is not sent (verified by a manual call).
decode_search_response() returns the same JSON-shaped dict that the REST JSON mapping would give,
so safe_browsing.parse_response() keeps doing all verification (full-hash match, TTL, attributes).

Field numbers: googleapis google/security/safebrowsing/v5/safebrowsing.proto (Apache-2.0)
  SearchHashesResponse: 1 full_hashes (repeated FullHash), 2 cache_duration (google.protobuf.Duration)
  FullHash: 1 full_hash (bytes), 2 full_hash_details (repeated FullHashDetail)
  FullHashDetail: 1 threat_type (ThreatType enum), 2 attributes (repeated ThreatAttribute enum)
and protocolbuffers google/protobuf/duration.proto: 1 seconds (int64), 2 nanos (int32).
Every malformed input raises ValueError (never a partial or "no match" result).
"""

import base64

# Unknown enum numbers stay ints; parse_response then ignores that detail (forward compatible).
THREAT_TYPES = {0: "THREAT_TYPE_UNSPECIFIED", 1: "MALWARE", 2: "SOCIAL_ENGINEERING",
                3: "UNWANTED_SOFTWARE", 4: "POTENTIALLY_HARMFUL_APPLICATION"}
THREAT_ATTRIBUTES = {0: "THREAT_ATTRIBUTE_UNSPECIFIED", 1: "CANARY", 2: "FRAME_ONLY"}

VARINT, I64, LEN, I32 = 0, 1, 2, 5
MAX_FIELD_NUMBER = (1 << 29) - 1
MAX_DURATION_SECONDS = 315_576_000_000  # Duration range in duration.proto


def _varint(data: bytes, pos: int) -> tuple[int, int]:
    result = 0
    for index in range(10):
        if pos >= len(data):
            raise ValueError("Truncated varint")
        byte = data[pos]
        pos += 1
        if index == 9 and byte > 1:
            raise ValueError("Varint exceeds 64 bits")
        result |= (byte & 0x7F) << (7 * index)
        if not byte & 0x80:
            return result, pos
    raise ValueError("Varint too long")


def _fields(data: bytes):
    """Yield (field number, wire type, value): int for VARINT, bytes for LEN/I32/I64."""
    pos = 0
    while pos < len(data):
        key, pos = _varint(data, pos)
        number, wire = key >> 3, key & 7
        if not 1 <= number <= MAX_FIELD_NUMBER:
            raise ValueError("Invalid field number")
        if wire == VARINT:
            value, pos = _varint(data, pos)
        elif wire == LEN:
            length, pos = _varint(data, pos)
            if length > len(data) - pos:
                raise ValueError("Length exceeds input")
            value, pos = data[pos:pos + length], pos + length
        elif wire in (I64, I32):
            size = 8 if wire == I64 else 4
            if size > len(data) - pos:
                raise ValueError("Truncated fixed field")
            value, pos = data[pos:pos + size], pos + size
        else:
            # 3/4 are deprecated groups, 6/7 are invalid.
            raise ValueError("Unsupported wire type")
        yield number, wire, value


def _expect(wire: int, expected: int) -> None:
    if wire != expected:
        raise ValueError("Wire type mismatch")


def _enum_name(value: int, names: dict[int, str]):
    return names.get(value, value)


def _duration(data: bytes) -> str:
    seconds = nanos = 0
    for number, wire, value in _fields(data):
        if number == 1:
            _expect(wire, VARINT)
            seconds = value
        elif number == 2:
            _expect(wire, VARINT)
            nanos = value
    # Negative int64/int32 arrive as huge unsigned varints; both are rejected here.
    if seconds > MAX_DURATION_SECONDS or nanos > 999_999_999:
        raise ValueError("Duration out of range")
    if not nanos:
        return f"{seconds}s"
    return f"{seconds}.{nanos:09d}".rstrip("0") + "s"


def _detail(data: bytes, unknown: list[int] | None) -> dict:
    threat = 0
    attributes: list = []
    for number, wire, value in _fields(data):
        if number == 1:
            _expect(wire, VARINT)
            threat = value  # singular: last value wins
        elif number == 2:
            if wire == VARINT:  # unpacked repeated enum
                attributes.append(_enum_name(value, THREAT_ATTRIBUTES))
            elif wire == LEN:  # packed repeated enum (proto3 default)
                pos = 0
                while pos < len(value):
                    item, pos = _varint(value, pos)
                    attributes.append(_enum_name(item, THREAT_ATTRIBUTES))
            else:
                raise ValueError("Wire type mismatch")
        elif unknown is not None:
            unknown.append(number)
    return {"threatType": _enum_name(threat, THREAT_TYPES), "attributes": attributes}


def _full_hash(data: bytes, unknown: list[int] | None) -> dict:
    digest = b""
    details = []
    for number, wire, value in _fields(data):
        if number == 1:
            _expect(wire, LEN)
            digest = value  # singular: last value wins; length is checked by parse_response
        elif number == 2:
            _expect(wire, LEN)
            details.append(_detail(value, unknown))
        elif unknown is not None:
            unknown.append(number)
    return {"fullHash": base64.b64encode(digest).decode("ascii"), "fullHashDetails": details}


def decode_search_response(data: bytes, unknown: list[int] | None = None) -> dict:
    """Decode SearchHashesResponse into the REST JSON shape. Unknown field numbers go to `unknown`."""
    records = []
    duration_parts = []
    for number, wire, value in _fields(data):
        if number == 1:
            _expect(wire, LEN)
            records.append(_full_hash(value, unknown))
        elif number == 2:
            _expect(wire, LEN)
            # A repeated singular message field merges, which equals parsing the concatenation.
            duration_parts.append(value)
        elif unknown is not None:
            unknown.append(number)
    body: dict = {"fullHashes": records}
    if duration_parts:
        body["cacheDuration"] = _duration(b"".join(duration_parts))
    return body
