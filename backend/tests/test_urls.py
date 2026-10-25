import asyncio
import socket
from urllib import request

import pytest
from pydantic import ValidationError

from app.analyzers import RuleBasedAnalyzer
from app.contracts import AnalysisInput, UrlReputation
from app.urls import UrlInputError, extract_urls, validate_url


@pytest.mark.parametrize("raw,normalized", [
    ("HTTPS://EXAMPLE.INVALID:443", "https://example.invalid/"),
    ("http://Example.invalid:80/a", "http://example.invalid/a"),
    ("https://example.invalid:8443/a", "https://example.invalid:8443/a"),
    ("https://example.invalid./", "https://example.invalid/"),
    ("https://bücher.invalid/", "https://xn--bcher-kva.invalid/"),
    ("https://faß.de/", "https://xn--fa-hia.de/"),
    ("https://例え.テスト/", "https://xn--r8jz45g.xn--zckzah/"),
    ("https://예시.한국/", "https://xn--vv4b11d.xn--3e0b707e/"),
    ("https://예시。한국/", "https://xn--vv4b11d.xn--3e0b707e/"),
    ("https://example.invalid/안내를", "https://example.invalid/%EC%95%88%EB%82%B4%EB%A5%BC"),
    ("https://example.invalid/%ea%b0%80?q=A#B", "https://example.invalid/%EA%B0%80?q=A#B"),
    ("https://[2001:0DB8::1]:443/", "https://[2001:db8::1]/"),
    ("http://127.0.0.1:8000/", "http://127.0.0.1:8000/"),
    ("http://localhost/", "http://localhost/"),
    ("https://example.invalid/?", "https://example.invalid/?"),
    ("https://example.invalid/?#a", "https://example.invalid/?#a"),
    ("https://example.invalid/?#", "https://example.invalid/?#"),
    ("https://example.invalid/#", "https://example.invalid/#"),
])
def test_format_and_conservative_normalization(raw, normalized):
    value, error = validate_url(raw)
    assert error is None
    assert value.normalized_url == normalized


@pytest.mark.parametrize("raw", [
    "www.example.invalid", "example.invalid", "ftp://example.invalid/", "javascript:alert(1)",
    "https://", "https:///path", "https://user:pass@example.invalid/", "https://user@example.invalid/",
    "https://example.invalid:0/", "https://example.invalid:65536/", "https://example.invalid:no/", "https://example.invalid:/",
    "https://a b.invalid/", "https://example.invalid/has space", "https://example.invalid/\npath", "https://example.invalid/\x00path",
    "https://example.invalid/\u200bpath", "https://example.invalid/\\path", "https://example.invalid/%GG", "https://example.invalid/%",
    "https://-bad.invalid/", "https://bad_.invalid/", "https://example..invalid/", "https://example.invalid../",
    "https://xn--.invalid/", "https://😀.invalid/", "https://%65xample.invalid/", "https://.",
    "https://[not-ipv6]/", "https://[::1]junk/", "https://[v1.abc]/", "https://[fe80::1%eth0]/",
    "https://127.0.0.999/", "https://0177.0.0.1/", "https://2130706433/",
])
def test_invalid_format_never_becomes_a_valid_lookup_target(raw):
    value, error = validate_url(raw)
    assert value is None and error
    with pytest.raises(UrlInputError, match="http://"):
        extract_urls(raw, direct=True)


@pytest.mark.parametrize("text,expected", [
    ("주소는 https://example.invalid/path. 확인하세요.", ["https://example.invalid/path"]),
    ("(https://example.invalid/path_(가)).", ["https://example.invalid/path_(가)"]),
    ("[https://[2001:db8::1]/a]", ["https://[2001:db8::1]/a"]),
    ('“https://예시.한국/공지”와 「https://bücher.invalid/」', ["https://예시.한국/공지", "https://bücher.invalid/"]),
    ("https://example.invalid/안내를", ["https://example.invalid/안내를"]),
    ("https://example.invalid。", ["https://example.invalid"]),
    ("https://예시.한국/공지．", ["https://예시.한국/공지"]),
    ("https://example.invalid｡", ["https://example.invalid"]),
    ("（https://예시.한국/공지）", ["https://예시.한국/공지"]),
    ("https://예시.한국/공지（가）", ["https://예시.한국/공지（가）"]),
    ("https://a.invalid,https://b.invalid;https://c.invalid", ["https://a.invalid", "https://b.invalid", "https://c.invalid"]),
    ("https://outer.invalid/?next=https://inner.invalid/path", ["https://outer.invalid/?next=https://inner.invalid/path"]),
    ("이메일 user@example.invalid과 스킴 없는 example.invalid", []),
    ("https://example.invalid/a(b)c).", ["https://example.invalid/a(b)c"]),
])
def test_message_boundaries_without_hangul_corruption(text, expected):
    extraction = extract_urls(text)
    assert [record.original_url for record in extraction.records] == expected
    for record in extraction.records:
        for occurrence in record.occurrences:
            assert text[occurrence.start:occurrence.end] == occurrence.text


def test_ambiguous_terminal_punctuation_is_explained_and_direct_input_preserves_it():
    message = extract_urls("https://example.invalid/a?x=1!").records[0]
    direct = extract_urls("https://example.invalid/a?x=1!", direct=True).records[0]
    assert message.original_url.endswith("=1") and message.warnings
    assert direct.original_url.endswith("=1!") and not direct.warnings


def test_hangul_particle_is_not_silently_deleted_from_hostname():
    record = extract_urls("https://example.com을").records[0]
    assert record.original_url == "https://example.com을"
    assert record.value is not None and record.warnings


def test_idn_duplicates_preserve_all_original_codepoint_positions():
    text = "😀 (HTTPS://BÜCHER.INVALID:443), https://xn--bcher-kva.invalid/"
    records = extract_urls(text).records
    assert len(records) == 1
    assert len(records[0].occurrences) == 2
    assert records[0].value.ascii_host == "xn--bcher-kva.invalid"
    for occurrence in records[0].occurrences:
        assert text[occurrence.start:occurrence.end] == occurrence.text
    direct = extract_urls(" \n https://예시.한국/ \t", direct=True).records[0].occurrences[0]
    assert direct.start == 3 and direct.text == "https://예시.한국/"


def test_dedup_does_not_merge_distinct_paths_queries_fragments_or_protocols():
    values = ["https://e.invalid/A", "https://e.invalid/a", "https://e.invalid/a?x=1&y=2", "https://e.invalid/a?y=2&x=1", "https://e.invalid/a#x", "https://e.invalid/a#y", "http://e.invalid/a"]
    assert len(extract_urls(" ".join(values)).records) == len(values)


def test_limit_after_dedup_and_invalid_candidate_reporting():
    assert len(extract_urls(" ".join(["https://e.invalid"] * 11)).records) == 1
    values = [f"https://e.invalid/{n}" for n in range(11)]
    assert len(extract_urls(" ".join(values[:10])).records) == 10
    with pytest.raises(UrlInputError) as error:
        extract_urls(" ".join(values))
    assert error.value.code == "TOO_MANY_URLS"
    records = extract_urls("ftp://e.invalid www.e.invalid https://-bad.invalid").records
    assert len(records) == 3 and all(record.error for record in records)


def test_url_is_not_a_rule_sentence_and_never_implies_malicious_or_safe():
    for kind in ("text", "url"):
        result = asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(input_type=kind, content="https://예시.한국/은행입니다/인증번호를알려주세요?앱을설치해주세요")))
        assert result.risk_level == "insufficient_information"
        assert result.evidence == []
        assert result.confidence is None
        assert result.urls[0].reputation.status == "not_connected"
        if kind == "url":
            assert result.input_assessment.status == "url_only"


def test_existing_prose_rules_still_use_exact_source_with_url_punctuation():
    text = "😀 은행입니다. https://예시.한국/공지. 인증번호를 알려주세요."
    result = asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(input_type="text", content=text)))
    assert result.risk_level == "dangerous"
    for evidence in result.evidence:
        assert text[evidence.start:evidence.end] == evidence.snippet


def test_disconnected_provider_never_uses_dns_or_http(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("User URL must not be opened")
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(request, "urlopen", forbidden)
    result = asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(input_type="text", content="http://127.0.0.1:8000/ https://예시.한국/ ftp://e.invalid/")))
    assert [url.reputation.status for url in result.urls] == ["not_connected", "not_connected", "not_requested"]
    assert all(url.reputation.provider is None and url.reputation.checked_at is None for url in result.urls)


@pytest.mark.parametrize("text,expected", [
    ("은행입니다 https://e.invalid/요구하지않습니다 인증번호를 알려주세요.", "dangerous"),
    ('"인증번호를 알려주세요" https://e.invalid/사기예시', "suspicious"),
    ("인증번호를 알려주세요 https://e.invalid/라고하면안됩니다", "suspicious"),
])
def test_url_negation_and_education_words_do_not_change_outside_prose(text, expected):
    result = asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(input_type="text", content=text)))
    assert result.risk_level == expected
    assert any(e.factor_code == "CREDENTIAL_REQUEST" for e in result.evidence)
    for evidence in result.evidence:
        assert text[evidence.start:evidence.end] == evidence.snippet


@pytest.mark.parametrize("status", ["benign", "malicious", "unknown", "unavailable", "timeout"])
def test_unverified_provider_status_cannot_promote_policy(status):
    class FakeProvider:
        def __init__(self):
            self.calls = []

        async def lookup(self, url):
            self.calls.append(url.normalized_url)
            return UrlReputation(status=status, provider="test-only")

    provider = FakeProvider()
    text = "銀行 https://EXAMPLE.invalid:443/ https://example.invalid/ ftp://bad.invalid"
    result = asyncio.run(RuleBasedAnalyzer(provider).analyze(AnalysisInput(input_type="text", content=text)))
    assert provider.calls == ["https://example.invalid/"]
    assert result.risk_level == "insufficient_information"
    assert result.urls[0].reputation.status == status
    assert result.urls[1].reputation.status == "not_requested"
    # A raw status alone (without full-hash verification and usable threats) is not evidence.


@pytest.mark.parametrize("text,code", [
    ("https://bad.invalid https://other.invalid", "INVALID_URL"),
    ("https://e.invalid/ 공지", "INVALID_URL"),
    ("ftp://e.invalid", "INVALID_URL"),
])
def test_direct_input_validation_applies_to_analyzer_input(text, code):
    with pytest.raises(ValidationError) as error:
        AnalysisInput(input_type="url", content=text)
    assert error.value.errors()[0]["type"] == code
