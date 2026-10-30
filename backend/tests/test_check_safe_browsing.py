"""수동 확인 스크립트의 동작 검증. httpx.MockTransport만 쓰고 실제 Google은 호출하지 않는다."""

import base64
from hashlib import sha256

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


def malware_protobuf():
    digest = next(iter(HASHES.full_hashes))  # 테스트 URL 표현 중 하나의 전체 해시
    entry = (
        b"\x0a\x20" + digest  # FullHash 필드 1 full_hash, LEN 32
        + b"\x12\x02"         # FullHash 필드 2 full_hash_details, LEN 2
        + b"\x08\x01"         #   threat_type varint 1 = MALWARE
    )
    return (
        b"\x0a" + bytes([len(entry)]) + entry  # 응답 필드 1 full_hashes, LEN 38
        + b"\x12\x03\x08\xac\x02"            # 응답 필드 2 cache_duration, LEN 3: seconds 300
    )


def test_default_run_protobuf_match_shows_structure_and_verdict(capsys):
    code, requests = run(lambda request: httpx.Response(200, headers={"content-type": "application/x-protobuf"}, content=malware_protobuf()))
    output = capsys.readouterr().out
    assert code == 0 and len(requests) == 1
    assert "alt" not in requests[0].url.params and requests[0].headers["x-goog-api-key"] == KEY
    assert "HTTP 상태: 200" in output and "Content-Type: application/x-protobuf" in output
    assert "protobuf 구조: full_hashes 1개, cache_duration 300s" in output
    assert "[0] full_hash 길이 32바이트, details 1개 (threat_type: MALWARE; attributes: 0개)" in output
    assert "status=malicious, reason=full_hash_match" in output and "위협 유형: MALWARE" in output
    assert "[확인] 전체 해시와 위협 유형이 일치했어요" in output
    assert_no_secrets(output)


def test_default_run_protobuf_empty_is_guidance(capsys):
    code, _ = run(lambda request: httpx.Response(200, headers={"content-type": "application/x-protobuf"},
                                                 content=b"\x12\x03\x08\xac\x02"))  # cache_duration 300s만
    output = capsys.readouterr().out
    assert code == 0 and "protobuf 구조: full_hashes 0개, cache_duration 300s" in output
    assert "status=unknown, reason=no_match" in output and "v5에서 일치하지 않을 수 있어요" in output
    assert "[실패]" not in output


def test_default_run_protobuf_parse_failure_prints_size_only(capsys):
    content = b"\x0a\x05\x00"  # full_hashes 길이 5인데 1바이트만 있음
    code, _ = run(lambda request: httpx.Response(200, headers={"content-type": "application/x-protobuf"}, content=content))
    output = capsys.readouterr().out
    assert code == 1 and "해석 실패(형식 오류) / 본문 크기: 3 바이트" in output
    assert "reason=invalid_response" in output and "protobuf 구조" not in output and "[중요]" not in output
    assert content.hex() not in output
    assert_no_secrets(output)


def test_default_run_unsupported_content_type(capsys):
    code, _ = run(lambda request: httpx.Response(200, headers={"content-type": "text/html"}, content=b"<html></html>"))
    output = capsys.readouterr().out
    assert code == 1 and "Content-Type: text/html" in output and "reason=invalid_response" in output
    assert "지원하지 않는 응답 형식이에요" in output and "<html>" not in output


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


SECRET_MESSAGE = f"Invalid value at 'hash_prefixes[3]' (TYPE_BYTES), Base64 decoding failed for \"ab+/cd\" key={KEY} https://example.invalid/leak"


def google_error(status="INVALID_ARGUMENT", message=SECRET_MESSAGE, details=None, code=400):
    return {"error": {"code": code, "message": message, "status": status, "details": details or []}}


def assert_no_error_text(output: str):
    assert_no_secrets(output)
    for leaked in ("Invalid value", "decoding failed", "ab+/cd", "example.invalid", "leak", "secret-description", "meta-value"):
        assert leaked not in output


def test_bad_prefix_400_prints_only_short_classification(capsys):
    details = [{"@type": "type.googleapis.com/google.rpc.BadRequest", "fieldViolations": [
        {"field": "hash_prefixes[3]", "description": "secret-description " + KEY}]}]
    code, requests = run(lambda request: httpx.Response(400, json=google_error(details=details)))
    output = capsys.readouterr().out
    assert code == 1 and len(requests) == 1
    assert "HTTP 상태: 400" in output and "reason=http_error" in output
    assert "error.code: 400" in output and "error.status: INVALID_ARGUMENT" in output
    assert "message_mentions_base64: true" in output and "message_mentions_api_key: false" in output
    assert "error.details[0]: @type=BadRequest fieldViolations.field=[hash_prefixes[3]]" in output
    assert "해시 접두사(형식)를 가리켜요" in output and "API 키 관련" not in output
    assert_no_error_text(output)


def test_invalid_key_400_is_identified_without_message(capsys):
    details = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID",
                "domain": "googleapis.com", "metadata": {"service": "meta-value"}}]
    body = google_error(message=f"API key not valid. Please pass a valid API key. {KEY}", details=details)
    code, _ = run(lambda request: httpx.Response(400, json=body))
    output = capsys.readouterr().out
    assert code == 1 and "error.details[0]: @type=ErrorInfo reason=API_KEY_INVALID" in output
    assert "message_mentions_api_key: true" in output and "message_mentions_base64: false" in output
    assert "API 키 관련 표시" in output and "API key not valid" not in output
    assert_no_error_text(output)


@pytest.mark.parametrize("value", ["lower_case", "TOO_LONG_" * 10, "HAS SPACE", 123])
def test_unexpected_values_are_omitted(value, capsys):
    details = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": value}]
    run(lambda request: httpx.Response(400, json=google_error(status=value, details=details)))
    output = capsys.readouterr().out
    assert "error.status: (형식 밖 값 생략)" in output and "reason=(형식 밖 값 생략)" in output
    if isinstance(value, str):
        assert value not in output


@pytest.mark.parametrize("response,expected", [
    (httpx.Response(400, headers={"content-type": "text/html"}, content=b"<html>" + KEY.encode() + b"</html>"), "JSON이 아니에요 (Content-Type: text/html)"),
    (httpx.Response(400, headers={"content-type": "application/json"}, content=b"not json " + KEY.encode()), "JSON이 아니에요"),
    (httpx.Response(400, headers={"content-type": "application/json"}, content=b"[1]"), "error 객체가 없어요"),
    (httpx.Response(400, headers={"content-type": "application/json"}, content=b'{"error": {"message": "' + b"x" * (16 * 1024) + b'"}}'), "16 KiB를 넘어 분석하지 않았어요"),
])
def test_non_json_missing_and_oversized_bodies(response, expected, capsys):
    code, _ = run(lambda request: response)
    output = capsys.readouterr().out
    assert code == 1 and expected in output and "<html>" not in output
    assert_no_secrets(output)


def test_probe_sends_only_the_official_example_prefix(capsys):
    code, requests = run(lambda request: httpx.Response(200, headers=JSON, json={"cacheDuration": "60s"}),
                         argv=("--live", "--probe", "official-example"))
    output = capsys.readouterr().out
    assert code == 0 and len(requests) == 1
    assert requests[0].url.params.get_list("hashPrefixes") == ["WwuJdQ"]
    assert "공식 예시 접두사 1개만 조회" in output and "보낸 접두사 개수: 1개" in output
    assert "키와 기본 요청은 정상" in output and "testsafebrowsing" not in output
    assert KEY not in output


def test_probe_reports_key_error(capsys):
    details = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "API_KEY_INVALID"}]
    code, requests = run(lambda request: httpx.Response(400, json=google_error(details=details, message="API key not valid")),
                         argv=("--live", "--probe", "official-example"))
    output = capsys.readouterr().out
    assert code == 1 and len(requests) == 1
    assert "reason=API_KEY_INVALID" in output and "[실패]" in output and "API key not valid" not in output


def test_probe_network_error_is_reported(capsys):
    def fail(request):
        raise httpx.ConnectError(f"{request.url} {KEY}", request=request)
    code, _ = run(fail, argv=("--live", "--probe", "official-example"))
    output = capsys.readouterr().out
    assert code == 1 and "네트워크 오류" in output and KEY not in output


def test_app_transport_still_does_not_read_error_bodies():
    """진단은 스크립트 전용이다. 앱 전송기는 오류 본문을 읽지 않고 상태 코드만 넘긴다."""
    import asyncio

    class Unreadable(httpx.AsyncByteStream):
        async def __aiter__(self):
            raise AssertionError("app transport must not read error bodies")
            yield b""

    async def go():
        transport = safe_browsing_http.HttpxHashSearchTransport(KEY, timeout=1.0, transport=httpx.MockTransport(
            lambda request: httpx.Response(400, stream=Unreadable())))
        try:
            return await transport.search(("WwuJdQ",))
        finally:
            await transport.aclose()
    response = asyncio.run(go())
    assert response.status_code == 400 and response.body == {}


def test_details_summary_line(capsys):
    details = [{"@type": "type.googleapis.com/google.rpc.ErrorInfo", "reason": "SOMETHING"},
               {"@type": "type.googleapis.com/google.rpc.BadRequest"}, "not a dict"]
    run(lambda request: httpx.Response(400, json=google_error(details=details)))
    output = capsys.readouterr().out
    assert "error.details: 3개 (@type: ErrorInfo, BadRequest, (없음))" in output
    run(lambda request: httpx.Response(400, json=google_error(details=[])))
    assert "error.details: 없음" in capsys.readouterr().out
    run(lambda request: httpx.Response(400, json={"error": {"code": 400, "status": "INVALID_ARGUMENT"}}))
    assert "error.details: 없음" in capsys.readouterr().out


# ---- --probe official-example --variant ----

def variant_argv(name):
    return ("--live", "--probe", "official-example", "--variant", name)


@pytest.mark.parametrize("name,expected_params,key_header,accept", [
    ("no-alt", [("hashPrefixes", "WwuJdQ")], True, "*/*"),
    ("key-query", [("key", KEY), ("hashPrefixes", "WwuJdQ"), ("alt", "json")], False, "application/json"),
    ("padded", [("hashPrefixes", "WwuJdQ=="), ("alt", "json")], True, "application/json"),
    ("official-exact", [("key", KEY), ("hashPrefixes", "WwuJdQ")], False, "*/*"),
])
def test_variant_request_shapes(name, expected_params, key_header, accept, capsys):
    code, requests = run(lambda request: httpx.Response(200, headers=JSON, json={"cacheDuration": "60s"}), argv=variant_argv(name))
    output = capsys.readouterr().out
    assert code == 0 and len(requests) == 1
    request = requests[0]
    assert request.method == "GET" and request.content == b""
    assert f"{request.url.scheme}://{request.url.host}{request.url.path}" == "https://safebrowsing.googleapis.com/v5/hashes:search"
    assert request.url.params.multi_items() == expected_params
    assert (request.headers.get("x-goog-api-key") == KEY) is key_header
    if not key_header:
        assert "x-goog-api-key" not in request.headers
    assert request.headers["accept"] == accept
    if name == "padded":
        assert b"hashPrefixes=WwuJdQ%3D%3D" in request.url.raw_path
    assert f"요청 변형 {name}" in output and "보낸 접두사 개수: 1개" in output
    assert "HTTP 상태: 200" in output and "cacheDuration: 60s" in output and "[확인]" in output
    assert KEY not in output


def test_unknown_variant_is_rejected_before_any_call(capsys):
    _, requests = None, []
    with pytest.raises(SystemExit) as exit_info:
        check_safe_browsing.main(list(variant_argv("other")), env=LIVE_ENV,
                                 transport=httpx.MockTransport(lambda request: requests.append(request)))
    assert exit_info.value.code == 2 and requests == []
    assert "invalid choice" in capsys.readouterr().err


def test_variant_requires_probe(capsys):
    code, requests = run(lambda request: httpx.Response(200), argv=("--live", "--variant", "no-alt"))
    assert code == 2 and requests == []
    assert "--probe official-example과 함께만" in capsys.readouterr().out


def test_variant_other_non_json_200_is_reported_without_decoding(capsys):
    code, _ = run(lambda request: httpx.Response(200, headers={"content-type": "text/plain"}, content=b"hello"),
                  argv=variant_argv("no-alt"))
    output = capsys.readouterr().out
    assert code == 0 and "Content-Type: text/plain" in output
    assert "본문 크기: 5 바이트" in output and "200, JSON이 아니에요" in output and "protobuf 구조" not in output


PROTOBUF = {"content-type": "application/x-protobuf"}
PROBE_DIGEST = sha256(b"ptos-probe-digest").digest()
PROTO_49 = (
    b"\x0a\x2a"                  # 응답 필드 1 full_hashes, LEN, 길이 42
    + b"\x0a\x20" + PROBE_DIGEST   # FullHash 필드 1 full_hash, LEN, 길이 32
    + b"\x12\x02\x08\x01"        # full_hash_details LEN 2: threat_type 1 = MALWARE
    + b"\x12\x02\x08\x02"        # full_hash_details LEN 2: threat_type 2 = SOCIAL_ENGINEERING
    + b"\x12\x03\x08\xac\x02"    # 응답 필드 2 cache_duration, LEN 3: seconds 300
)


def assert_no_probe_bytes(output: str):
    for secret in (PROBE_DIGEST.hex(), base64.b64encode(PROBE_DIGEST).decode(), base64.b64encode(PROBE_DIGEST[:4]).decode().rstrip("="),
                   PROTO_49.hex(), base64.b64encode(PROTO_49).decode(), PROBE_DIGEST[:4].hex()):
        assert secret not in output


@pytest.mark.parametrize("name", ["no-alt", "official-exact"])
def test_variant_protobuf_49_bytes_structure_summary(name, capsys):
    assert len(PROTO_49) == 49
    code, _ = run(lambda request: httpx.Response(200, headers=PROTOBUF, content=PROTO_49), argv=variant_argv(name))
    output = capsys.readouterr().out
    assert code == 0 and "본문 크기: 49 바이트" in output
    assert "protobuf 구조: full_hashes 1개, cache_duration 300s, 모르는 필드 0개" in output
    assert "[0] full_hash 길이 32바이트, details 2개 (threat_type: MALWARE, SOCIAL_ENGINEERING; attributes: 0개)" in output
    assert "200, JSON이 아니에요" not in output
    assert_no_probe_bytes(output)
    assert KEY not in output


def test_variant_protobuf_empty_result(capsys):
    code, _ = run(lambda request: httpx.Response(200, headers=PROTOBUF, content=b"\x12\x03\x08\xac\x02"),  # cache_duration 300s만
                  argv=variant_argv("no-alt"))
    output = capsys.readouterr().out
    assert code == 0 and "protobuf 구조: full_hashes 0개, cache_duration 300s" in output
    assert "결과 없음이에요 (안전 판정 아님)" in output


def test_variant_protobuf_unknown_threat_and_fields(capsys):
    entry = (b"\x0a\x20" + PROBE_DIGEST  # full_hash LEN 32
             + b"\x12\x04"               # full_hash_details LEN 4
             + b"\x08\x09"               # threat_type 9 = 모르는 번호
             + b"\x10\x01")              # attributes unpacked 1 = CANARY
    data = b"\x78\x01" + b"\x0a" + bytes([len(entry)]) + entry + b"\x12\x02\x08\x05"  # 모르는 필드 15 + full_hashes + 5초
    run(lambda request: httpx.Response(200, headers=PROTOBUF, content=data), argv=variant_argv("no-alt"))
    output = capsys.readouterr().out
    assert "full_hashes 1개, cache_duration 5s, 모르는 필드 1개" in output
    assert "threat_type: 알 수 없는 번호 9; attributes: 1개" in output


@pytest.mark.parametrize("content", [
    b"\x0a\x30" + PROBE_DIGEST,  # full_hashes 길이 48인데 32바이트만 있음
    b"\x0b",                     # wire type 3 (group) 미지원
    PROTO_49[:-1],               # 마지막 바이트가 잘림
])
def test_variant_protobuf_parse_failure_prints_only_failure_and_size(content, capsys):
    code, _ = run(lambda request: httpx.Response(200, headers=PROTOBUF, content=content), argv=variant_argv("no-alt"))
    output = capsys.readouterr().out
    assert code == 0
    assert f"해석 실패(형식 오류) / 본문 크기: {len(content)} 바이트" in output
    assert "protobuf 구조" not in output and "full_hash 길이" not in output
    assert_no_probe_bytes(output)
    assert content.hex() not in output and base64.b64encode(content).decode() not in output


def _leaky_responses():
    leak = f"https://safebrowsing.googleapis.com/v5/hashes:search?key={KEY}&hashPrefixes=WwuJdQ"
    def connect_error(request):
        raise httpx.ConnectError(f"cannot connect {request.url}", request=request)
    def read_timeout(request):
        raise httpx.ReadTimeout(f"timed out {request.url}", request=request)
    def runtime_error(request):
        raise RuntimeError(f"unexpected {request.url} {KEY}")
    return [
        lambda request: httpx.Response(200, headers=JSON, json={"cacheDuration": "60s", "echo": str(request.url)}),
        lambda request: httpx.Response(400, json=google_error(message=f"bad {request.url}", details=[
            {"@type": "type.googleapis.com/google.rpc.BadRequest", "fieldViolations": [{"field": "key", "description": str(request.url)}]}])),
        lambda request: httpx.Response(400, headers={"content-type": "text/html"}, content=str(request.url).encode()),
        lambda request: httpx.Response(302, headers={"location": leak}),
        connect_error, read_timeout, runtime_error,
    ]


@pytest.mark.parametrize("name", ["key-query", "official-exact"])
@pytest.mark.parametrize("handler", _leaky_responses())
def test_key_in_query_never_leaks_to_output_exceptions_or_logs(name, handler, capsys, caplog):
    import logging
    records = []
    class Capture(logging.Handler):
        def emit(self, record):
            records.append(record.getMessage())
    direct = Capture(level=logging.DEBUG)
    for logger_name in ("httpx", "httpcore"):
        logging.getLogger(logger_name).addHandler(direct)
    caplog.set_level(logging.DEBUG)
    try:
        code, requests = run(handler, argv=variant_argv(name))
    finally:
        for logger_name in ("httpx", "httpcore"):
            logging.getLogger(logger_name).removeHandler(direct)
    captured = capsys.readouterr()
    assert len(requests) == 1 and requests[0].url.params["key"] == KEY  # the key really was in the URL
    for text in (captured.out, captured.err, caplog.text, "\n".join(records)):
        assert KEY not in text and "key=" not in text and "hashPrefixes=" not in text
        assert "safebrowsing.googleapis.com/v5" not in text
    assert code in (0, 1)
    if code == 1 and "전송 단계 문제" in captured.out:
        assert any(f"전송 단계 문제: {name_}" in captured.out for name_ in ("ConnectError", "ReadTimeout", "RuntimeError"))


def test_variant_timeout_reports_class_name_only(capsys):
    import asyncio
    async def hang(request):
        await asyncio.Event().wait()
    code, _ = run(hang, argv=(*variant_argv("official-exact"), "--timeout", "0.05"))
    output = capsys.readouterr().out
    assert code == 1 and "전송 단계 문제: TimeoutError" in output and KEY not in output


def test_script_locks_down_httpx_logging():
    import logging
    for logger_name in ("httpx", "httpcore"):
        logger = logging.getLogger(logger_name)
        assert logger.level == logging.WARNING and logger.propagate is False


def test_script_uses_the_app_transport():
    assert check_safe_browsing.HttpxHashSearchTransport is safe_browsing_http.HttpxHashSearchTransport
