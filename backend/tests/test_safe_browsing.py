import asyncio
import base64
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
import pytest

from app.analyzers import RuleBasedAnalyzer
from app.contracts import AnalysisInput
from app.main import create_app
from app.safe_browsing import PROVIDER, SafeBrowsingV5Provider, SearchResponse
from app.safe_browsing_urls import hash_url
from app.urls import ValidatedUrl

URL = "https://example.invalid/path?private=token"
VALUE = ValidatedUrl(normalized_url=URL, ascii_host="example.invalid")
DIGEST = next(iter(hash_url(URL).full_hashes))


def reply(digest=DIGEST, threat="SOCIAL_ENGINEERING", attributes=None, ttl="300s"):
    return {"cacheDuration": ttl, "fullHashes": [{
        "fullHash": base64.b64encode(digest).decode(),
        "fullHashDetails": [{"threatType": threat, "attributes": attributes or []}],
    }]}


class FakeTransport:
    def __init__(self, body=None, status=200):
        self.response = SearchResponse(status, body if body is not None else {"cacheDuration": "300s"})
        self.calls = []

    async def search(self, prefixes):
        self.calls.append(prefixes)
        return self.response


def lookup(transport, **kwargs):
    return asyncio.run(SafeBrowsingV5Provider(transport, **kwargs).lookup(VALUE))


def test_complete_hash_match_and_only_four_byte_prefixes_cross_boundary():
    fake = FakeTransport(reply())
    result = lookup(fake)
    assert result.status == "malicious" and result.full_hash_verified
    assert result.threat_types == ["SOCIAL_ENGINEERING"] and result.reason == "full_hash_match"
    assert fake.calls == [tuple(base64.b64encode(p).decode().rstrip("=") for p in hash_url(URL).prefixes)]
    # Unpadded standard Base64 (official overview example: hashPrefixes=WwuJdQ).
    assert all(len(p) == 6 and "=" not in p and len(base64.b64decode(p + "==")) == 4 for p in fake.calls[0])
    assert URL not in repr(fake.calls) and "private" not in repr(fake.calls)


def test_prefix_collision_does_not_prove_a_full_hash_match():
    other = DIGEST[:4] + bytes(b ^ 255 for b in DIGEST[4:])
    result = lookup(FakeTransport(reply(other)))
    assert result.status == "unknown" and result.reason == "no_match"
    assert not result.full_hash_verified and result.threat_types == []


@pytest.mark.parametrize("body", [{"cacheDuration": "60s"}, {"cacheDuration": "60s", "fullHashes": []}])
def test_http_200_empty_is_unknown_not_benign(body):
    assert lookup(FakeTransport(body)).status == "unknown"


@pytest.mark.parametrize("status,expected,reason", [(401, "auth_error", "authentication_failed"), (403, "auth_error", "authentication_failed"), (429, "rate_limited", "provider_rate_limit"), (500, "unavailable", "server_error"), (503, "unavailable", "server_error"), (404, "unavailable", "http_error"), (302, "unavailable", "http_error")])
def test_http_error_classification(status, expected, reason):
    result = lookup(FakeTransport({"error": "sensitive data must not escape"}, status))
    assert (result.status, result.reason) == (expected, reason)
    assert result.checked_at is None and "sensitive" not in result.model_dump_json()


@pytest.mark.parametrize("threat,attributes", [("FUTURE_THREAT", []), (0, []), ("MALWARE", ["FUTURE_ATTRIBUTE"]), ("MALWARE", ["CANARY"]), ("MALWARE", ["FRAME_ONLY"]), ("MALWARE", ["THREAT_ATTRIBUTE_UNSPECIFIED"])])
def test_unusable_details_are_not_enforced(threat, attributes):
    result = lookup(FakeTransport(reply(threat=threat, attributes=attributes)))
    assert result.status == "unknown" and result.reason == "unsupported_details"
    assert not result.full_hash_verified


def test_unknown_detail_does_not_hide_other_valid_detail():
    body = reply(threat="FUTURE_THREAT")
    body["fullHashes"][0]["fullHashDetails"].append({"threatType": "MALWARE"})
    result = lookup(FakeTransport(body))
    assert result.status == "malicious" and result.threat_types == ["MALWARE"]


@pytest.mark.parametrize("body", [{}, {"cacheDuration": "-1s"}, {"cacheDuration": "NaNs"}, {"cacheDuration": "1.1234567890s"}, {"cacheDuration": "999999999999999s"}, {"cacheDuration": "60s", "fullHashes": None}, {"cacheDuration": "60s", "fullHashes": [{"fullHash": "not base64"}]}, reply(b"short"), reply(b"\0" * 32), {"cacheDuration": "60s", "fullHashes": [None]}])
def test_malformed_reply_is_not_no_match(body):
    result = lookup(FakeTransport(body))
    assert result.status == "unavailable" and result.reason == "invalid_response"


def test_transport_failure_timeout_and_cancel_are_distinct():
    class Failing:
        async def search(self, prefixes):
            raise RuntimeError(URL + "secret-key")

    class Hanging:
        async def search(self, prefixes):
            await asyncio.Event().wait()

    assert lookup(Failing()).reason == "transport_error"
    assert lookup(Hanging(), timeout=0.01).status == "timeout"

    async def cancel():
        provider = SafeBrowsingV5Provider(Hanging())
        task = asyncio.create_task(provider.lookup(VALUE))
        await asyncio.sleep(0)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        assert not provider._lock.locked()
    asyncio.run(cancel())


@pytest.mark.parametrize("positive", [False, True])
def test_response_ttl_caches_positive_and_negative_prefixes_then_expires(positive):
    async def run():
        now = [0.0]
        epoch = datetime(2026, 1, 1, tzinfo=timezone.utc)
        fake = FakeTransport(reply(ttl="1.5s") if positive else {"cacheDuration": "1.5s"})
        provider = SafeBrowsingV5Provider(fake, monotonic=lambda: now[0], utcnow=lambda: epoch + timedelta(seconds=now[0]), per_minute=10)
        first = await provider.lookup(VALUE)
        assert not first.cache_hit and first.cache_expires_at == epoch + timedelta(seconds=1.5)
        assert len(provider._cache) == len(hash_url(URL).prefixes)
        now[0] = 1.49
        second = await provider.lookup(VALUE)
        assert second.cache_hit and second.checked_at == first.checked_at and len(fake.calls) == 1
        now[0] = 1.5
        fake.response = SearchResponse(200, {"cacheDuration": "7s"})
        third = await provider.lookup(VALUE)
        assert not third.cache_hit and third.status == "unknown" and len(fake.calls) == 2
        assert third.cache_expires_at == epoch + timedelta(seconds=8.5)
        # Cache keys/values contain no input URL or original text.
        assert all(isinstance(p, bytes) and len(p) == 4 for p in provider._cache)
        assert "example.invalid" not in repr(provider._cache)
    asyncio.run(run())


def test_concurrent_duplicate_requests_are_coalesced():
    async def run():
        fake = FakeTransport()
        provider = SafeBrowsingV5Provider(fake)
        results = await asyncio.gather(*(provider.lookup(VALUE) for _ in range(5)))
        assert len(fake.calls) == 1 and sum(r.cache_hit for r in results) == 4
    asyncio.run(run())


def test_cache_capacity_does_not_evict_live_entries_and_refetch():
    async def run():
        fake = FakeTransport()
        provider = SafeBrowsingV5Provider(fake, cache_capacity=len(hash_url(URL).prefixes))
        await provider.lookup(VALUE)
        other = ValidatedUrl("https://other.invalid/a", "other.invalid")
        result = await provider.lookup(other)
        assert result.reason == "cache_capacity" and len(fake.calls) == 1
        assert (await provider.lookup(VALUE)).cache_hit
    asyncio.run(run())


def test_cached_host_threat_survives_missing_path_prefix_and_call_limit():
    async def run():
        from hashlib import sha256
        digest = sha256(b"example.invalid/").digest()
        fake = FakeTransport(reply(digest))
        provider = SafeBrowsingV5Provider(fake, per_day=1)
        assert (await provider.lookup(VALUE)).status == "malicious"
        other = ValidatedUrl("https://example.invalid/another/new/path", "example.invalid")
        result = await provider.lookup(other)
        assert result.status == "malicious" and result.cache_hit
        assert len(fake.calls) == 1
    asyncio.run(run())


def test_partial_negative_cache_that_expires_during_other_lookup_is_not_complete():
    async def run():
        now = [0.0]
        fake = FakeTransport({"cacheDuration": "1s"})
        provider = SafeBrowsingV5Provider(fake, monotonic=lambda: now[0], per_minute=10)
        await provider.lookup(VALUE)
        now[0] = 0.5
        async def slow_reply(prefixes):
            fake.calls.append(prefixes)
            now[0] = 1.5
            return SearchResponse(200, {"cacheDuration": "10s"})
        fake.search = slow_reply
        other = ValidatedUrl("https://example.invalid/new/path", "example.invalid")
        result = await provider.lookup(other)
        assert result.status == "unavailable" and result.reason == "cache_expired_during_lookup"
        assert (await provider.lookup(other)).status == "unknown"
    asyncio.run(run())


def test_many_slow_urls_preserve_text_evidence_within_api_deadline():
    class Hanging:
        async def search(self, prefixes):
            await asyncio.Event().wait()
    provider = SafeBrowsingV5Provider(Hanging(), timeout=0.01)
    text = "은행입니다. 인증번호를 알려주세요. " + " ".join(f"https://sample{n}.invalid/" for n in range(10))
    with TestClient(create_app(analyzer_factory=lambda: RuleBasedAnalyzer(provider), analysis_timeout=1)) as client:
        response = client.post("/api/v1/analyses", json={"input_type": "text", "content": text})
    assert response.status_code == 200
    body = response.json()
    assert body["risk_level"] == "dangerous" and body["confidence"] is None
    assert all(url["reputation"]["status"] == "timeout" for url in body["urls"])
    assert body["analysis_stages"][2]["status"] == "unavailable"
    assert any(e["factor_code"] == "CREDENTIAL_REQUEST" for e in body["evidence"])


def test_minute_and_rolling_day_budget_includes_errors_but_allows_cached_reads():
    async def run():
        now = [0.0]
        fake = FakeTransport(status=500)
        provider = SafeBrowsingV5Provider(fake, per_minute=1, per_day=2, monotonic=lambda: now[0])
        assert (await provider.lookup(VALUE)).reason == "server_error"
        assert (await provider.lookup(VALUE)).reason == "local_limit"
        now[0] = 60
        assert (await provider.lookup(VALUE)).reason == "server_error"
        now[0] = 120
        assert (await provider.lookup(VALUE)).reason == "local_limit"
        now[0] = 86400
        fake.response = SearchResponse(200, {"cacheDuration": "300s"})
        assert (await provider.lookup(VALUE)).status == "unknown"
        assert (await provider.lookup(VALUE)).cache_hit
        assert len(fake.calls) == 3
    asyncio.run(run())


@pytest.mark.parametrize("text,kind,expected", [
    (URL, "url", "dangerous"),
    ("회의는 오후 3시에 시작합니다. " + URL, "text", "dangerous"),
    ("은행입니다. 인증번호를 알려주세요. " + URL, "text", "dangerous"),
    ("링크를 클릭해주세요. " + URL, "text", "dangerous"),
    ("사기 예방 교육: 인증번호를 알려주지 마세요. " + URL, "text", "dangerous"),
])
def test_verified_match_adds_exact_url_evidence_without_inventing_sender_claim(text, kind, expected):
    provider = SafeBrowsingV5Provider(FakeTransport(reply()))
    result = asyncio.run(RuleBasedAnalyzer(provider).analyze(AnalysisInput(input_type=kind, content=text)))
    assert result.risk_level == expected and result.confidence is None
    matches = [e for e in result.evidence if e.source == "url_reputation"]
    assert len(matches) == 1 and matches[0].snippet == URL
    assert "발신자나 사기 여부를 확정한 것은 아니에요" in result.explanation
    assert "조회하지 않았어요" not in result.explanation
    for evidence in result.evidence:
        assert text[evidence.start:evidence.end] == evidence.snippet
    if text.startswith("은행"):
        assert any(e.source == "rule" and e.factor_code == "CREDENTIAL_REQUEST" for e in result.evidence)


def test_normalization_failure_is_distinct_and_never_calls_transport():
    fake = FakeTransport()
    result = asyncio.run(SafeBrowsingV5Provider(fake).lookup(ValidatedUrl("ftp://unsupported.invalid/", "unsupported.invalid")))
    assert result.status == "unavailable" and result.reason == "normalization_failed"
    assert fake.calls == []


@pytest.mark.parametrize("status,body", [(200, {"cacheDuration": "60s"}), (401, {}), (403, {}), (429, {}), (503, {})])
@pytest.mark.parametrize("text,expected", [(URL, "insufficient_information"), ("은행입니다. 인증번호를 알려주세요. " + URL, "dangerous"), ("인증번호를 알려주세요. " + URL, "suspicious")])
def test_unknown_or_failed_lookup_never_clears_rules_or_implies_normal(status, body, text, expected):
    result = asyncio.run(RuleBasedAnalyzer(SafeBrowsingV5Provider(FakeTransport(body, status))).analyze(AnalysisInput(input_type="text", content=text)))
    assert result.risk_level == expected and result.confidence is None
    assert all(e.source == "rule" for e in result.evidence)


def test_default_application_cannot_connect_even_when_key_is_present(monkeypatch, caplog):
    import socket
    from urllib import request
    def forbidden(*args, **kwargs):
        raise AssertionError("Network is forbidden")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(request, "urlopen", forbidden)
    monkeypatch.delenv("GOOGLE_SAFE_BROWSING_API_KEY", raising=False)
    for key, reason in [(None, "key_missing"), ("private-test-key-do-not-log", "policy_pending")]:
        if key:
            monkeypatch.setenv("GOOGLE_SAFE_BROWSING_API_KEY", key)
        with TestClient(create_app()) as client:
            body = client.post("/api/v1/analyses", json={"input_type": "url", "content": URL}).json()
        reputation = body["urls"][0]["reputation"]
        assert reputation["status"] == "not_connected" and reputation["reason"] == reason
        assert "private-test-key" not in str(body)
    assert URL not in caplog.text and "private-test-key" not in caplog.text


def test_fake_provider_runs_through_real_api_contract_without_exposing_transport_exception(caplog):
    provider = SafeBrowsingV5Provider(FakeTransport(reply()))
    with TestClient(create_app(analyzer_factory=lambda: RuleBasedAnalyzer(provider))) as client:
        response = client.post("/api/v1/analyses", json={"input_type": "ocr_text", "content": URL, "ocr_confirmed": True})
    body = response.json()
    assert response.status_code == 200 and body["risk_level"] == "dangerous"
    assert body["urls"][0]["reputation"]["provider"] == PROVIDER
    assert body["evidence"][0]["source"] == "url_reputation"
    assert URL not in caplog.text
