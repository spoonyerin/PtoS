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


def match_body(digest=DIGEST):
    return {"cacheDuration": "300s", "fullHashes": [{
        "fullHash": base64.b64encode(digest).decode(),
        "fullHashDetails": [{"threatType": "MALWARE"}],
    }]}


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


def test_request_carries_only_unpadded_prefixes_and_header_key():
    result, requests = run_lookup(lambda request: httpx.Response(200, headers=JSON, json=match_body()))
    assert result.status == "malicious" and result.threat_types == ["MALWARE"]
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and request.content == b""
    assert f"{request.url.scheme}://{request.url.host}{request.url.path}" == SEARCH_ENDPOINT
    assert set(request.url.params.keys()) == {"hashPrefixes", "alt"}
    assert request.url.params["alt"] == "json"
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
            lambda request: seen.append(request) or httpx.Response(200, headers=JSON, json={"cacheDuration": "1s"})))
        await transport.search(("+/8A/w", "WwuJdQ"))
        await transport.aclose()
        return seen[0]
    request = asyncio.run(go())
    assert b"hashPrefixes=%2B%2F8A%2Fw&hashPrefixes=WwuJdQ&alt=json" in request.url.raw_path
    assert request.url.params.get_list("hashPrefixes") == ["+/8A/w", "WwuJdQ"]


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
    httpx.Response(200, headers={"content-type": "application/x-protobuf"}, content=b"\x0a\x00"),
    httpx.Response(200, content=b"{}"),
    httpx.Response(200, headers=JSON, content=b"not json"),
    httpx.Response(200, headers=JSON, content=b"[]"),
    httpx.Response(200, headers=JSON, content=b" " * (MAX_RESPONSE_BYTES + 1)),
])
def test_unusable_200_body_is_invalid_response(response):
    result, _ = run_lookup(lambda request: response)
    assert (result.status, result.reason) == ("unavailable", "invalid_response")


def test_non_json_content_type_is_kept_for_manual_diagnostics():
    async def go():
        transport = HttpxHashSearchTransport(KEY, timeout=1.0, transport=httpx.MockTransport(
            lambda request: httpx.Response(200, headers={"content-type": "application/x-protobuf"}, content=b"")))
        try:
            await transport.search(("WwuJdQ",))
        finally:
            await transport.aclose()
    with pytest.raises(TransportResponseError) as error:
        asyncio.run(go())
    assert error.value.content_type == "application/x-protobuf"


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
