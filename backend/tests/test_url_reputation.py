"""켜는 조건(키 + PTOS_SAFE_BROWSING_MODE=live-noncommercial)과 앱 연결. 실제 Google 호출 없음."""

import logging

from fastapi.testclient import TestClient
import pytest

from app import safe_browsing_http
from app.safe_browsing import SafeBrowsingV5Provider
from app.main import create_app
from app.url_reputation import API_KEY_ENV, LIVE_MODE, MODE_ENV, TIMEOUT_ENV, DisconnectedReputationProvider, configured_reputation_provider

KEY = "fake-test-key-do-not-log"
URL = "https://example.invalid/path?q=1"


@pytest.fixture
def no_transport(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("HTTP transport must not be built")
    monkeypatch.setattr(safe_browsing_http, "HttpxHashSearchTransport", forbidden)


@pytest.mark.parametrize("env,reason", [
    ({}, "key_missing"),
    ({API_KEY_ENV: "   "}, "key_missing"),
    ({MODE_ENV: LIVE_MODE}, "key_missing"),
    ({API_KEY_ENV: KEY}, "policy_pending"),
    ({API_KEY_ENV: KEY, MODE_ENV: ""}, "policy_pending"),
    ({API_KEY_ENV: KEY, MODE_ENV: "1"}, "policy_pending"),
    ({API_KEY_ENV: KEY, MODE_ENV: "true"}, "policy_pending"),
    ({API_KEY_ENV: KEY, MODE_ENV: "live"}, "policy_pending"),
    ({API_KEY_ENV: KEY, MODE_ENV: "LIVE-NONCOMMERCIAL"}, "policy_pending"),
    ({API_KEY_ENV: KEY, MODE_ENV: " live-noncommercial"}, "policy_pending"),
    ({API_KEY_ENV: KEY, MODE_ENV: "live-noncommercial "}, "policy_pending"),
])
def test_key_and_exact_mode_are_both_required(env, reason, no_transport):
    provider = configured_reputation_provider(env, max_timeout=5.0)
    assert isinstance(provider, DisconnectedReputationProvider) and provider.reason == reason


@pytest.mark.parametrize("value", ["abc", "0", "-1", "5", "5.0", "10", "nan", "inf"])
def test_invalid_timeout_keeps_reputation_off(value, no_transport, caplog):
    env = {API_KEY_ENV: KEY, MODE_ENV: LIVE_MODE, TIMEOUT_ENV: value}
    provider = configured_reputation_provider(env, max_timeout=5.0)
    assert isinstance(provider, DisconnectedReputationProvider) and provider.reason == "invalid_config"
    assert KEY not in caplog.text


@pytest.mark.parametrize("value,expected", [(None, 1.0), ("", 1.0), ("2.5", 2.5), ("0.2", 0.2)])
def test_live_mode_builds_provider_with_configured_timeout(value, expected, caplog):
    env = {API_KEY_ENV: KEY, MODE_ENV: LIVE_MODE}
    if value is not None:
        env[TIMEOUT_ENV] = value
    with caplog.at_level(logging.WARNING):
        provider = configured_reputation_provider(env, max_timeout=5.0)
    assert isinstance(provider, SafeBrowsingV5Provider)
    assert provider._timeout == expected and provider._transport._timeout == expected
    assert "lookups are ON" in caplog.text and KEY not in caplog.text and KEY not in repr(provider._transport)
    # Building the provider makes no connection; the HTTP client is created on first lookup.
    assert provider._transport._client is None


@pytest.mark.parametrize("env,expected", [
    ({}, "off"),
    ({API_KEY_ENV: KEY}, "off"),
    ({MODE_ENV: LIVE_MODE}, "off"),
    ({API_KEY_ENV: KEY, MODE_ENV: "1"}, "off"),
    ({API_KEY_ENV: KEY, MODE_ENV: LIVE_MODE, TIMEOUT_ENV: "abc"}, "off"),
    ({API_KEY_ENV: KEY, MODE_ENV: LIVE_MODE}, "live"),
    ({API_KEY_ENV: KEY, MODE_ENV: LIVE_MODE, TIMEOUT_ENV: "2"}, "live"),
])
def test_ready_reports_only_whether_lookups_are_live(env, expected, monkeypatch):
    for name, value in env.items():
        monkeypatch.setenv(name, value)
    with TestClient(create_app()) as client:
        response = client.get("/api/v1/health/ready")
    # Only on/off: no key, timeout, provider name or provider state. No external call is made for ready.
    assert response.json() == {"status": "ready", "mode": "rules", "url_reputation": expected}
    assert KEY not in response.text and "timeout" not in response.text and "google" not in response.text.lower()


def test_ready_is_off_for_injected_analyzers():
    with TestClient(create_app(analyzer_factory=lambda: None)) as client:
        assert client.get("/api/v1/health/ready").json()["url_reputation"] == "off"


def test_app_without_live_mode_never_builds_transport(monkeypatch, no_transport):
    monkeypatch.setenv(API_KEY_ENV, KEY)
    with TestClient(create_app()) as client:
        body = client.post("/api/v1/analyses", json={"input_type": "url", "content": URL}).json()
    assert body["urls"][0]["reputation"]["reason"] == "policy_pending"
    assert body["analysis_stages"][2]["status"] == "not_connected"


def test_live_app_is_stopped_by_test_network_guard_and_keeps_rule_evidence(monkeypatch, no_external_network, caplog):
    """Self-test of tests/conftest.py: a live app really tries to connect and is blocked."""
    monkeypatch.setenv(API_KEY_ENV, KEY)
    monkeypatch.setenv(MODE_ENV, LIVE_MODE)
    app = create_app()
    text = "은행입니다. 인증번호를 알려주세요. " + URL
    with TestClient(app) as client:
        response = client.post("/api/v1/analyses", json={"input_type": "text", "content": text})
    body = response.json()
    assert response.status_code == 200 and body["risk_level"] == "dangerous"
    assert any(e["source"] == "rule" and e["factor_code"] == "CREDENTIAL_REQUEST" for e in body["evidence"])
    reputation = body["urls"][0]["reputation"]
    assert (reputation["status"], reputation["reason"]) == ("unavailable", "network_error")
    assert body["analysis_stages"][2]["status"] == "unavailable"
    assert no_external_network == ["safebrowsing.googleapis.com"]
    assert KEY not in response.text and KEY not in caplog.text and "example.invalid" not in caplog.text
    no_external_network.clear()  # expected attempt; any other test with an attempt fails
