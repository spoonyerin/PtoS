"""v5 SearchHashesResponse 직접 디코더 테스트.

고정 바이트는 protobuf 인코딩 규칙으로 직접 조립했다.
- 태그 1바이트 = (필드 번호 << 3) | wire type. wire type 0 = varint, 1 = 8바이트, 2 = 길이 구분(LEN), 5 = 4바이트.
- varint는 7비트씩 낮은 자리부터, 마지막 바이트를 뺀 나머지는 최상위 비트(0x80)가 켜져 있다.
- 필드 번호(safebrowsing.proto v5): 응답 1 full_hashes, 2 cache_duration / FullHash 1 full_hash, 2 full_hash_details /
  FullHashDetail 1 threat_type, 2 attributes / Duration 1 seconds, 2 nanos.
"""

import base64
from hashlib import sha256
import random

import pytest

from app.safe_browsing import parse_response
from app.safe_browsing_proto import decode_search_response

# 실제 URL과 무관한 테스트용 32바이트 해시.
DIGEST = sha256(b"ptos-proto-test").digest()
OTHER = sha256(b"ptos-proto-other").digest()
PREFIX = DIGEST[:4]

DURATION_300S = (
    b"\x12\x03"     # 응답 필드 2 cache_duration, LEN(0x12 = 2<<3|2), 길이 3
    b"\x08\xac\x02"  # Duration 필드 1 seconds, varint(0x08 = 1<<3|0), 300 = 0xac 0x02
)

DETAIL_MALWARE = (
    b"\x12\x02"  # FullHash 필드 2 full_hash_details, LEN, 길이 2
    b"\x08\x01"  # FullHashDetail 필드 1 threat_type, varint, 1 = MALWARE
)
DETAIL_SOCIAL = (
    b"\x12\x02"  # FullHash 필드 2 full_hash_details, LEN, 길이 2
    b"\x08\x02"  # threat_type varint 2 = SOCIAL_ENGINEERING
)

ENTRY_ONE_DETAIL = (
    b"\x0a\x20" + DIGEST  # FullHash 필드 1 full_hash, LEN(0x0a = 1<<3|2), 길이 32, 32바이트 해시
    + DETAIL_MALWARE      # 4바이트
)  # 합계 38바이트

ENTRY_TWO_DETAILS = ENTRY_ONE_DETAIL + DETAIL_SOCIAL  # 합계 42바이트

RESPONSE_ONE_MATCH = (
    b"\x0a\x26" + ENTRY_ONE_DETAIL  # 응답 필드 1 full_hashes, LEN, 길이 38(0x26)
    + DURATION_300S
)

# 수동 호출에서 받은 49바이트 응답과 같은 크기가 나오는 구조 예시: 해시 1개 + 상세 2개 + 300초.
RESPONSE_49_BYTES = (
    b"\x0a\x2a" + ENTRY_TWO_DETAILS  # 응답 필드 1 full_hashes, LEN, 길이 42(0x2a) → 2 + 42 = 44바이트
    + DURATION_300S                  # 5바이트 → 합계 49바이트
)


def test_empty_result_is_only_cache_duration():
    body = decode_search_response(DURATION_300S)
    assert body == {"fullHashes": [], "cacheDuration": "300s"}
    ttl, found, ignored = parse_response(body, (PREFIX,))
    assert ttl == 300 and found == {} and ignored == frozenset()


def test_one_match_round_trips_through_existing_parser():
    body = decode_search_response(RESPONSE_ONE_MATCH)
    assert body == {"cacheDuration": "300s", "fullHashes": [{
        "fullHash": base64.b64encode(DIGEST).decode(),
        "fullHashDetails": [{"threatType": "MALWARE", "attributes": []}]}]}
    _, found, _ = parse_response(body, (PREFIX,))
    assert found == {DIGEST: frozenset({"MALWARE"})}


def test_49_byte_example_structure():
    assert len(RESPONSE_49_BYTES) == 49
    body = decode_search_response(RESPONSE_49_BYTES)
    assert len(body["fullHashes"]) == 1
    assert [d["threatType"] for d in body["fullHashes"][0]["fullHashDetails"]] == ["MALWARE", "SOCIAL_ENGINEERING"]
    assert parse_response(body, (PREFIX,))[1] == {DIGEST: frozenset({"MALWARE", "SOCIAL_ENGINEERING"})}


def test_multiple_full_hashes():
    other_entry = (
        b"\x0a\x20" + OTHER  # full_hash, LEN 32
        + b"\x12\x02\x08\x03"  # detail: threat_type 3 = UNWANTED_SOFTWARE
    )
    data = (
        b"\x0a\x26" + ENTRY_ONE_DETAIL  # 첫 번째 full_hashes
        + b"\x0a\x26" + other_entry       # 두 번째 full_hashes
        + DURATION_300S
    )
    body = decode_search_response(data)
    assert [r["fullHash"] for r in body["fullHashes"]] == [base64.b64encode(DIGEST).decode(), base64.b64encode(OTHER).decode()]
    assert body["fullHashes"][1]["fullHashDetails"] == [{"threatType": "UNWANTED_SOFTWARE", "attributes": []}]


@pytest.mark.parametrize("detail,expected", [
    (b"\x12\x06"          # full_hash_details, LEN, 길이 6
     b"\x08\x01"          # threat_type 1 = MALWARE
     b"\x12\x02\x01\x02", # attributes, packed LEN 길이 2: 1 = CANARY, 2 = FRAME_ONLY
     ["CANARY", "FRAME_ONLY"]),
    (b"\x12\x06"          # full_hash_details, LEN, 길이 6
     b"\x08\x01"          # threat_type 1 = MALWARE
     b"\x10\x01"          # attributes, unpacked varint(0x10 = 2<<3|0) 1 = CANARY
     b"\x10\x02",         # attributes, unpacked varint 2 = FRAME_ONLY
     ["CANARY", "FRAME_ONLY"]),
    (b"\x12\x04"          # full_hash_details, LEN, 길이 4
     b"\x08\x01"          # threat_type 1 = MALWARE
     b"\x10\x07",         # attributes, unpacked varint 7 = 아직 모르는 번호
     [7]),
])
def test_packed_unpacked_and_unknown_attributes_are_not_enforced(detail, expected):
    entry = b"\x0a\x20" + DIGEST + detail  # full_hash LEN 32 + detail
    data = b"\x0a" + bytes([len(entry)]) + entry + DURATION_300S  # full_hashes LEN
    body = decode_search_response(data)
    assert body["fullHashes"][0]["fullHashDetails"][0]["attributes"] == expected
    _, found, ignored = parse_response(body, (PREFIX,))
    assert found == {DIGEST: frozenset()} and ignored == {DIGEST}


@pytest.mark.parametrize("threat_bytes,expected", [
    (b"\x08\x09", 9),                          # threat_type varint 9 = 아직 모르는 번호
    (b"", "THREAT_TYPE_UNSPECIFIED"),          # threat_type 없음 = 기본값 0
    (b"\x08\x00", "THREAT_TYPE_UNSPECIFIED"),  # threat_type varint 0
])
def test_unknown_or_unspecified_threat_is_ignored_by_parser(threat_bytes, expected):
    entry = b"\x0a\x20" + DIGEST + b"\x12" + bytes([len(threat_bytes)]) + threat_bytes  # full_hash + detail
    data = b"\x0a" + bytes([len(entry)]) + entry + DURATION_300S
    body = decode_search_response(data)
    assert body["fullHashes"][0]["fullHashDetails"][0]["threatType"] == expected
    _, found, ignored = parse_response(body, (PREFIX,))
    assert found == {DIGEST: frozenset()} and DIGEST in ignored


@pytest.mark.parametrize("duration,expected", [
    (b"\x12\x00", "0s"),                                   # cache_duration LEN 0: 빈 Duration = 0초
    (b"\x12\x02\x08\x01", "1s"),                           # seconds varint 1
    (b"\x12\x08"                                           # cache_duration LEN 8 (= 2 + 1 + 5)
     b"\x08\x01"                                           # seconds varint 1 (2바이트)
     b"\x10\x80\xca\xb5\xee\x01", "1.5s"),                 # nanos 태그 1바이트 + varint 500000000 (5바이트)
    (b"\x12\x03"                                           # cache_duration LEN 3
     b"\x10\xe8\x07", "0.000001s"),                        # nanos varint 1000 = 0xe8 0x07
    (b"\x12\x05"                                           # cache_duration LEN 5
     b"\x08\xac\x02"                                       # seconds varint 300
     b"\x18\x01", "300s"),                                 # Duration의 모르는 필드 3, varint 1 → 무시
    (b"\x12\x02\x08\x05" + b"\x12\x02\x08\x07", "7s"),    # cache_duration 두 번 → 병합, seconds 마지막 값 7
])
def test_duration_formats_match_rest_json(duration, expected):
    body = decode_search_response(duration)
    assert body["cacheDuration"] == expected
    assert parse_response(body, (PREFIX,))[0] == float(expected[:-1])


def test_missing_duration_is_invalid_for_existing_parser():
    data = b"\x0a\x26" + ENTRY_ONE_DETAIL  # full_hashes만 있고 cache_duration 없음
    body = decode_search_response(data)
    assert "cacheDuration" not in body
    with pytest.raises(ValueError):
        parse_response(body, (PREFIX,))


def test_unknown_fields_are_skipped_and_recorded():
    entry = (
        b"\x0a\x20" + DIGEST   # full_hash
        + b"\x18\x05"          # FullHash의 모르는 필드 3, varint 5
        + b"\x12\x04"          # full_hash_details, LEN 4
        + b"\x08\x01"          #   threat_type 1 = MALWARE
        + b"\x28\x07"          #   FullHashDetail의 모르는 필드 5, varint 7
    )
    data = (
        b"\x78\x01"                               # 응답의 모르는 필드 15, varint 1
        + b"\x82\x01\x02\xff\xff"                 # 응답의 모르는 필드 16, LEN(태그 varint 0x82 0x01 = 130 = 16<<3|2), 길이 2
        + b"\x1d\x01\x02\x03\x04"                 # 응답의 모르는 필드 3, 4바이트 고정(0x1d = 3<<3|5)
        + b"\x21" + b"\x00" * 8                   # 응답의 모르는 필드 4, 8바이트 고정(0x21 = 4<<3|1)
        + b"\x0a" + bytes([len(entry)]) + entry   # full_hashes
        + DURATION_300S
    )
    unknown: list[int] = []
    body = decode_search_response(data, unknown)
    assert sorted(unknown) == [3, 3, 4, 5, 15, 16]
    assert parse_response(body, (PREFIX,))[1] == {DIGEST: frozenset({"MALWARE"})}


def test_singular_full_hash_last_value_wins():
    entry = (
        b"\x0a\x20" + OTHER    # full_hash 첫 값
        + b"\x0a\x20" + DIGEST  # full_hash 두 번째 값 → 이 값을 쓴다
        + DETAIL_MALWARE
    )
    data = b"\x0a" + bytes([len(entry)]) + entry + DURATION_300S
    assert decode_search_response(data)["fullHashes"][0]["fullHash"] == base64.b64encode(DIGEST).decode()


@pytest.mark.parametrize("data", [
    b"\x0a",                          # full_hashes 태그 뒤 길이 없음
    b"\x0a\x05\x00",                  # 길이 5인데 1바이트만 있음
    b"\x0a\x80",                      # 길이 varint가 끝나지 않음
    b"\x0b",                          # wire type 3 (group 시작) 미지원
    b"\x0c",                          # wire type 4 (group 끝) 미지원
    b"\x0e\x00",                      # wire type 6 잘못된 값
    b"\x0f\x00",                      # wire type 7 잘못된 값
    b"\x02\x00",                      # 필드 번호 0, LEN
    b"\x08\x01",                      # full_hashes가 varint(wire type 불일치)
    b"\x10\x01",                      # cache_duration이 varint(wire type 불일치)
    b"\x1d\x00\x00",                  # 4바이트 고정 필드가 잘림
    b"\x21\x00\x00\x00",              # 8바이트 고정 필드가 잘림
    b"\x78" + b"\xff" * 10 + b"\x01", # 11바이트 varint
    b"\x78" + b"\xff" * 9 + b"\x02",  # 64비트를 넘는 10바이트 varint
    b"\x12\x0b\x08" + b"\xfb" + b"\xff" * 8 + b"\x01",  # seconds = -5 (10바이트 varint) → 음수 거부
    b"\x12\x07\x08\x81\xbc\xae\xce\x97\x09",            # seconds = 315576000001 → Duration 범위 초과
    b"\x12\x06\x10\x80\x94\xeb\xdc\x03",                # nanos = 1000000000 → 범위 초과
    b"\x12\x02\x08\x80",              # Duration 안의 seconds varint가 끝나지 않음
    b"\x0a\x04\x0a\x20\x00\x00",      # FullHash 안의 full_hash 길이 32인데 2바이트만 있음
    b"\x0a\x02\x08\x01",              # FullHash의 full_hash가 varint(wire type 불일치)
    b"\x0a\x04\x12\x02\x08\x80",      # FullHashDetail의 threat_type varint가 끝나지 않음
    b"\x0a\x04\x12\x02\x12\x80",      # FullHashDetail의 attributes LEN 길이 varint가 끝나지 않음
    b"\x0a\x05\x12\x03\x12\x01\x80",  # packed attributes 안의 varint가 끝나지 않음
    b"\x0a\x04\x12\x02\x0d\x00",      # threat_type이 4바이트 고정(wire type 불일치)
])
def test_malformed_input_raises_value_error(data):
    with pytest.raises(ValueError):
        decode_search_response(data)


def test_every_truncation_of_valid_response_is_value_error_or_valid_dict():
    for end in range(len(RESPONSE_49_BYTES)):
        try:
            body = decode_search_response(RESPONSE_49_BYTES[:end])
        except ValueError:
            continue
        assert isinstance(body, dict) and isinstance(body["fullHashes"], list)


def test_random_bytes_only_raise_value_error():
    rng = random.Random(20261028)
    for _ in range(5000):
        data = bytes(rng.randrange(256) for _ in range(rng.randrange(0, 80)))
        try:
            body = decode_search_response(data)
        except ValueError:
            continue
        assert isinstance(body, dict)
