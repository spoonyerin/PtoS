"""Live transport tests with httpx.MockTransport only. No real network or Google call."""

import asyncio
import base64
import logging

import httpx
import pytest

from app.safe_browsing import SEARCH_ENDPOINT, SafeBrowsingV5Provider, TransportResponseError
from app.safe_browsing_http import MAX_RESPONSE_BYTES, HttpxHashSearchTransport
from app.safe_browsing_urls import hash_url
from app.urls import ValidatedUrl

URL = "https://example.invalid/path?private=token"
VALUE = ValidatedUrl(normalized_url=URL, ascii_host="example.invalid")
DIGEST = next(iter(hash_url(URL).full_hashes))
KEY = "fake-test-key-do-not-log"
JSON = {"content-type": "application/json; charset=UTF-8"}
PROTOBUF = {"content-type": "application/x-protobuf"}


def match_body(digest=DIGEST):
    return {"cacheDuration": "300s", "fullHashes": [{
        "fullHash": base64.b64encode(digest).decode(),
        "fullHashDetails": [{"threatType": "MALWARE"}],
    }]}


# protobuf 고정 바이트 (태그 = 필드 번호 << 3 | wire type, 필드 번호는 safebrowsing.proto v5)
PROTO_EMPTY_300S = (
    b"\x12\x03"      # SearchHashesResponse 필드 2 cache_duration, LEN 3
    b"\x08\xac\x02"  # Duration 필드 1 seconds, varint 300
)


def proto_match(digest=DIGEST, detail=b"\x08\x01"):
    """full_hashes 1개 + cache_duration 300s. detail 기본값: threat_type varint 1 = MALWARE."""
    entry = (
        b"\x0a\x20" + digest                       # FullHash 필드 1 full_hash, LEN 32
        + b"\x12" + bytes([len(detail)]) + detail  # FullHash 필드 2 full_hash_details, LEN
    )
    return b"\x0a" + bytes([len(entry)]) + entry + PROTO_EMPTY_300S  # 응답 필드 1 full_hashes, LEN


def run_lookup(handler, **kwargs):
    requests = []

    def record(request):
        requests.append(request)
        return handler(request)

    async def go():
        transport = HttpxHashSearchTransport(KEY, timeout=1.0, transport=httpx.MockTransport(record))
        try:
            return await SafeBrowsingV5Provider(transport, **kwargs).lookup(VALUE)
        finally:
            await transport.aclose()
    return asyncio.run(go()), requests


def test_request_has_no_alt_or_json_accept_and_key_only_in_header():
    result, requests = run_lookup(lambda request: httpx.Response(200, headers=PROTOBUF, content=proto_match()))
    assert result.status == "malicious" and result.threat_types == ["MALWARE"] and result.full_hash_verified
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and request.content == b""
    assert f"{request.url.scheme}://{request.url.host}{request.url.path}" == SEARCH_ENDPOINT
    # Only hashPrefixes: alt=json with a JSON Accept got 400 INVALID_ARGUMENT in a manual call.
    assert set(request.url.params.keys()) == {"hashPrefixes"}
    assert b"alt=" not in request.url.raw_path and "key" not in request.url.params
    assert "json" not in request.headers.get("accept", "")
    sent = request.url.params.get_list("hashPrefixes")
    assert sent == [base64.b64encode(p).decode().rstrip("=") for p in hash_url(URL).prefixes]
    assert all("=" not in p and len(base64.b64decode(p + "==")) == 4 for p in sent)
    assert request.headers["x-goog-api-key"] == KEY
    # The key is never in the URL; the input URL, host, query and full hashes never leave.
    raw = str(request.url) + repr(dict(request.headers))
    assert KEY not in str(request.url)
    for secret in ("example.invalid", "private", "token", base64.b64encode(DIGEST).decode()):
        assert secret not in raw


def test_base64_special_characters_are_percent_encoded():
    async def go():
        seen = []
        transport = HttpxHashSearchTransport(KEY, timeout=1.0, transport=httpx.MockTransport(
            lambda request: seen.append(request) or httpx.Response(200, headers=PROTOBUF, content=PROTO_EMPTY_300S)))
        await transport.search(("+/8A/w", "WwuJdQ"))
        await transport.aclose()
        return seen[0]
    request = asyncio.run(go())
    assert request.url.raw_path.endswith(b"?hashPrefixes=%2B%2F8A%2Fw&hashPrefixes=WwuJdQ")
    assert request.url.params.get_list("hashPrefixes") == ["+/8A/w", "WwuJdQ"]


@pytest.mark.parametrize("content_type", ["application/x-protobuf", "application/x-protobuf; charset=binary", "APPLICATION/X-PROTOBUF"])
def test_protobuf_empty_200_is_unknown_not_safe(content_type):
    result, _ = run_lookup(lambda request: httpx.Response(200, headers={"content-type": content_type}, content=PROTO_EMPTY_300S))
    assert (result.status, result.reason) == ("unknown", "no_match") and not result.full_hash_verified


def test_protobuf_prefix_collision_is_not_a_match():
    other = DIGEST[:4] + bytes(b ^ 255 for b in DIGEST[4:])
    result, _ = run_lookup(lambda request: httpx.Response(200, headers=PROTOBUF, content=proto_match(other)))
    assert (result.status, result.reason) == ("unknown", "no_match")


@pytest.mark.parametrize("detail", [
    b"\x08\x09",              # threat_type 9 = 모르는 번호
    b"\x08\x00",              # threat_type 0 = THREAT_TYPE_UNSPECIFIED
    b"\x08\x01\x10\x01",      # MALWARE + attributes unpacked 1 = CANARY
    b"\x08\x01\x12\x01\x02",  # MALWARE + attributes packed LEN 1: 2 = FRAME_ONLY
])
def test_protobuf_unknown_or_unusable_details_are_not_enforced(detail):
    result, _ = run_lookup(lambda request: httpx.Response(200, headers=PROTOBUF, content=proto_match(detail=detail)))
    assert (result.status, result.reason) == ("unknown", "unsupported_details") and not result.full_hash_verified


def test_search_response_reports_media_type():
    async def go(headers, content):
        transport = HttpxHashSearchTransport(KEY, timeout=1.0, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers=headers, content=content)))
        try:
            return await transport.search(("WwuJdQ",))
        finally:
            await transport.aclose()
    proto = asyncio.run(go({"content-type": "application/x-protobuf; foo=bar"}, PROTO_EMPTY_300S))
    assert proto.content_type == "application/x-protobuf" and proto.body == {"fullHashes": [], "cacheDuration": "300s"}
    json_reply = asyncio.run(go(JSON, b'{"cacheDuration": "60s"}'))
    assert json_reply.content_type == "application/json" and json_reply.body == {"cacheDuration": "60s"}


def test_json_200_still_works_for_compatibility():
    result, _ = run_lookup(lambda request: httpx.Response(200, headers=JSON, json=match_body()))
    assert result.status == "malicious" and result.threat_types == ["MALWARE"]


def test_empty_200_is_unknown_not_safe():
    result, _ = run_lookup(lambda request: httpx.Response(200, headers=JSON, json={"cacheDuration": "60s"}))
    assert (result.status, result.reason) == ("unknown", "no_match") and not result.full_hash_verified


def test_prefix_collision_is_not_a_match():
    other = DIGEST[:4] + bytes(b ^ 255 for b in DIGEST[4:])
    result, _ = run_lookup(lambda request: httpx.Response(200, headers=JSON, json=match_body(other)))
    assert (result.status, result.reason) == ("unknown", "no_match")


@pytest.mark.parametrize("status,expected", [
    (401, ("auth_error", "authentication_failed")), (403, ("auth_error", "authentication_failed")),
    (429, ("rate_limited", "provider_rate_limit")), (500, ("unavailable", "server_error")),
    (503, ("unavailable", "server_error")), (400, ("unavailable", "http_error")),
    (404, ("unavailable", "http_error")), (302, ("unavailable", "http_error")),
])
def test_http_status_classification_without_following_redirects(status, expected):
    headers = {"location": "https://elsewhere.invalid/"} if status == 302 else {}
    result, requests = run_lookup(lambda request: httpx.Response(status, headers=headers, text="echo " + KEY))
    assert (result.status, result.reason) == expected
    assert len(requests) == 1 and KEY not in result.model_dump_json()


@pytest.mark.parametrize("response", [
    httpx.Response(200, headers=PROTOBUF, content=b"\x0b"),                 # protobuf wire type 3(group) 미지원
    httpx.Response(200, headers=PROTOBUF, content=PROTO_EMPTY_300S[:-1]),   # protobuf 잘림
    httpx.Response(200, headers=PROTOBUF, content=b"\x0a\x00"),             # FullHash에 해시 없음, cache_duration 없음
    httpx.Response(200, headers=PROTOBUF, content=b"\x00" * (MAX_RESPONSE_BYTES + 1)),
    httpx.Response(200, content=b"{}"),                                     # Content-Type 없음
    httpx.Response(200, headers={"content-type": "text/plain"}, content=PROTO_EMPTY_300S),
    httpx.Response(200, headers={"content-type": "application/octet-stream"}, content=PROTO_EMPTY_300S),
    httpx.Response(200, headers={"content-type": "application/x-protobuf-json"}, content=PROTO_EMPTY_300S),
    httpx.Response(200, headers=JSON, content=b"not json"),
    httpx.Response(200, headers=JSON, content=b"[]"),
    httpx.Response(200, headers=JSON, content=b" " * (MAX_RESPONSE_BYTES + 1)),
])
def test_unusable_200_body_is_invalid_response(response):
    result, _ = run_lookup(lambda request: response)
    assert (result.status, result.reason) == ("unavailable", "invalid_response")


@pytest.mark.parametrize("headers,content,size", [
    ({"content-type": "text/html"}, b"<html></html>", None),  # 지원하지 않는 형식: 본문을 읽지 않음
    (PROTOBUF, b"\x0a\x05\x00", 3),                           # protobuf 해석 실패: 크기만 보존
])
def test_unusable_content_type_and_size_are_kept_for_manual_diagnostics(headers, content, size):
    async def go():
        transport = HttpxHashSearchTransport(KEY, timeout=1.0, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers=headers, content=content)))
        try:
            await transport.search(("WwuJdQ",))
        finally:
            await transport.aclose()
    with pytest.raises(TransportResponseError) as error:
        asyncio.run(go())
    assert error.value.content_type == headers["content-type"] and error.value.size == size


@pytest.mark.parametrize("exception,expected", [
    (httpx.ConnectTimeout, ("timeout", "request_timeout")),
    (httpx.ReadTimeout, ("timeout", "request_timeout")),
    (httpx.ConnectError, ("unavailable", "network_error")),
    (httpx.ReadError, ("unavailable", "network_error")),
])
def test_network_failures_are_distinct(exception, expected):
    def fail(request):
        raise exception(f"failed {request.url} {KEY}", request=request)
    result, _ = run_lookup(fail)
    assert (result.status, result.reason) == expected


def test_slow_transport_hits_provider_deadline():
    async def go():
        async def hang(request):
            await asyncio.Event().wait()
        transport = HttpxHashSearchTransport(KEY, timeout=5.0, transport=httpx.MockTransport(hang))
        try:
            return await SafeBrowsingV5Provider(transport, timeout=0.01).lookup(VALUE)
        finally:
            await transport.aclose()
    result = asyncio.run(go())
    assert (result.status, result.reason) == ("timeout", "request_timeout")


def test_key_never_appears_in_repr_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    def fail(request):
        raise httpx.ConnectError(f"{request.url} {KEY}", request=request)
    run_lookup(lambda request: httpx.Response(200, headers=JSON, json=match_body()))
    run_lookup(fail)
    transport = HttpxHashSearchTransport(KEY, timeout=1.0)
    assert KEY not in repr(transport)
    asyncio.run(transport.aclose())
    assert KEY not in caplog.text and "example.invalid" not in caplog.text


@pytest.mark.parametrize("key,timeout", [("", 1.0), ("   ", 1.0), (KEY, 0), (KEY, -1)])
def test_invalid_configuration_is_rejected(key, timeout):
    with pytest.raises(ValueError):
        HttpxHashSearchTransport(key, timeout=timeout)
