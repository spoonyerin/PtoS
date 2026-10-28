"""수동 확인 스크립트의 동작 검증. httpx.MockTransport만 쓰고 실제 Google은 호출하지 않는다."""

import base64

import httpx
import pytest

import check_safe_browsing
from app import safe_browsing_http
from app.safe_browsing_urls import hash_url
from app.url_reputation import API_KEY_ENV, LIVE_MODE, MODE_ENV

KEY = "fake-test-key-do-not-log"
LIVE_ENV = {API_KEY_ENV: KEY, MODE_ENV: LIVE_MODE}
JSON = {"content-type": "application/json; charset=UTF-8"}
HASHES = hash_url(check_safe_browsing.TEST_URL)


def malware_reply():
    digest = next(iter(HASHES.full_hashes))
    return {"cacheDuration": "300s", "fullHashes": [{
        "fullHash": base64.b64encode(digest).decode(), "fullHashDetails": [{"threatType": "MALWARE"}]}]}


def run(handler, argv=("--live",), env=LIVE_ENV):
    requests = []
    def record(request):
        requests.append(request)
        return handler(request)
    code = check_safe_browsing.main(list(argv), env=env, transport=httpx.MockTransport(record))
    return code, requests


def assert_no_secrets(output: str):
    assert KEY not in output
    for prefix in HASHES.prefixes:
        assert base64.b64encode(prefix).decode().rstrip("=") not in output
    for digest in HASHES.full_hashes:
        assert base64.b64encode(digest).decode() not in output and digest.hex() not in output


@pytest.mark.parametrize("argv,env,message", [
    ([], LIVE_ENV, "--live 옵션이 없어요"),
    (["--live"], {API_KEY_ENV: KEY}, MODE_ENV),
    (["--live"], {API_KEY_ENV: KEY, MODE_ENV: "1"}, MODE_ENV),
    (["--live"], {MODE_ENV: LIVE_MODE}, API_KEY_ENV),
    (["--live", "--timeout", "0"], LIVE_ENV, "--timeout"),
    (["--live", "--timeout", "31"], LIVE_ENV, "--timeout"),
])
def test_refuses_without_live_flag_mode_and_key(argv, env, message, monkeypatch, capsys):
    def forbidden(*args, **kwargs):
        raise AssertionError("HTTP transport must not be built")
    monkeypatch.setattr(check_safe_browsing, "HttpxHashSearchTransport", forbidden)
    assert check_safe_browsing.main(argv, env=env) == 2
    output = capsys.readouterr().out
    assert message in output and "외부 호출을 하지 않았어요" in output


def test_match_reports_diagnostics_once_without_secrets(capsys):
    code, requests = run(lambda request: httpx.Response(200, headers=JSON, json=malware_reply()))
    output = capsys.readouterr().out
    assert code == 0 and len(requests) == 1
    assert "status=malicious, reason=full_hash_match" in output and "위협 유형: MALWARE" in output
    assert "HTTP 상태: 200" in output and "Content-Type: application/json" in output
    assert "cacheDuration: 300s" in output and "응답 시간:" in output and " ms" in output
    assert f"보낸 접두사 개수: {len(HASHES.prefixes)}개" in output
    assert check_safe_browsing.TEST_URL_SOURCE in output
    # Only the fixed test URL's prefixes were sent; the URL itself was never requested.
    assert requests[0].url.host == "safebrowsing.googleapis.com"
    assert "testsafebrowsing" not in str(requests[0].url)
    assert_no_secrets(output)


def test_empty_reply_is_guidance_not_error(capsys):
    code, _ = run(lambda request: httpx.Response(200, headers=JSON, json={"cacheDuration": "60s"}))
    output = capsys.readouterr().out
    assert code == 0 and "status=unknown, reason=no_match" in output
    assert "v5에서 일치하지 않을 수 있어요" in output and "오류가 아니에요" in output
    assert "[실패]" not in output


def test_protobuf_reply_is_reported_before_any_decoder(capsys):
    code, _ = run(lambda request: httpx.Response(200, headers={"content-type": "application/x-protobuf"}, content=b"\x12\x03\x08\xac\x02"))
    output = capsys.readouterr().out
    assert code == 1 and "Content-Type: application/x-protobuf" in output
    assert "protobuf일 수 있어요" in output and "reason=invalid_response" in output
    assert_no_secrets(output)


@pytest.mark.parametrize("status,reason", [(401, "authentication_failed"), (403, "authentication_failed"), (429, "provider_rate_limit"), (503, "server_error")])
def test_http_failures_are_reported(status, reason, capsys):
    code, requests = run(lambda request: httpx.Response(status, text="echo " + KEY))
    output = capsys.readouterr().out
    assert code == 1 and len(requests) == 1
    assert f"HTTP 상태: {status}" in output and f"reason={reason}" in output
    assert_no_secrets(output)


def test_network_error_is_reported(capsys):
    def fail(request):
        raise httpx.ConnectError(f"{request.url} {KEY}", request=request)
    code, _ = run(fail)
    output = capsys.readouterr().out
    assert code == 1 and "네트워크 오류" in output and "reason=network_error" in output
    assert_no_secrets(output)


def test_script_uses_the_app_transport():
    assert check_safe_browsing.HttpxHashSearchTransport is safe_browsing_http.HttpxHashSearchTransport
