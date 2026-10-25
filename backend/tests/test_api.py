import asyncio
import logging
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from app.contracts import AnalysisInput
from app.main import create_app


@pytest.fixture
def client():
    with TestClient(create_app()) as client:
        yield client


@pytest.mark.parametrize("text,level", [
    ("은행입니다. 인증번호를 알려주세요.", "dangerous"),
    ("앱을 설치해주세요.", "suspicious"),
    ("도서관은 내일 휴무입니다.", "insufficient_information"),
])
def test_input_drives_rule_results(client, text, level):
    response = client.post("/api/v1/analyses", json={"input_type": "text", "content": text})
    assert response.status_code == 200
    body = response.json()
    assert body["risk_level"] == level
    assert body["is_demo"] is False
    assert body["analysis_mode"] == "rules"
    assert body["confidence"] is None
    assert body["explanation"] and body["action_guidance"]
    assert "규칙 기반 개발 버전" in body["limitations"][0]
    assert body["analysis_version"] == "rules-reputation-dev-v1"
    assert body["analysis_stages"][1] == {"name": "lightweight_model", "status": "not_implemented"}
    for evidence in body["evidence"]:
        assert text[evidence["start"]:evidence["end"]] == evidence["snippet"]
    UUID(body["request_id"])
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize("update,code", [
    ({"content": ""}, "INVALID_INPUT"),
    ({"content": " \n\t"}, "INVALID_INPUT"),
    ({"content": "가" * 10_001}, "INPUT_TOO_LONG"),
    ({"content": 123}, "INVALID_INPUT"),
    ({"demo_scenario": "safe"}, "INVALID_INPUT"),
    ({"input_type": "url"}, "INVALID_URL"),
    ({"unknown": True}, "INVALID_INPUT"),
])
def test_validation(client, update, code):
    body = {"input_type": "text", "content": "비공개 메시지"} | update
    response = client.post("/api/v1/analyses", json=body)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == code
    assert response.json()["error"]["retryable"] is False
    assert "비공개 메시지" not in response.text
    assert "input" not in response.json()
    assert response.headers["cache-control"] == "no-store"


def test_max_unicode_length_and_raw_content_reaches_adapter():
    received = []

    class SpyAnalyzer:
        async def analyze(self, data):
            from app.analyzers import RuleBasedAnalyzer
            assert type(data) is AnalysisInput
            received.append(data.content)
            return await RuleBasedAnalyzer().analyze(data)

    with TestClient(create_app(lambda: SpyAnalyzer())) as client:
        content = "😀" * 10_000
        response = client.post("/api/v1/analyses", json={"input_type": "text", "content": content})
    assert response.status_code == 200
    assert received == [content]


def test_service_error_is_not_information_result(caplog):
    secret = "private-message-should-not-be-logged"

    class BrokenAnalyzer:
        async def analyze(self, data):
            raise RuntimeError(data.content)

    with TestClient(create_app(lambda: BrokenAnalyzer())) as client, caplog.at_level(logging.ERROR):
        response = client.post("/api/v1/analyses", json={"input_type": "text", "content": secret})
    assert response.status_code == 503
    assert response.json()["error"] == {"code": "ANALYSIS_UNAVAILABLE", "message": "서버에서 요청을 처리하지 못했어요. 잠시 후 다시 시도해주세요.", "retryable": True}
    assert "risk_level" not in response.json()
    assert secret not in response.text + caplog.text
    assert response.headers["cache-control"] == "no-store"


def test_timeout():
    class SlowAnalyzer:
        async def analyze(self, data):
            await asyncio.sleep(1)

    with TestClient(create_app(lambda: SlowAnalyzer(), analysis_timeout=0.01)) as client:
        response = client.post("/api/v1/analyses", json={"input_type": "text", "content": "확인할 문자"})
    assert response.status_code == 504
    assert response.json()["error"]["code"] == "ANALYSIS_TIMEOUT"


def test_malformed_json_and_health(client):
    response = client.post("/api/v1/analyses", content="{", headers={"Content-Type": "application/json"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_INPUT"
    assert client.get("/api/v1/health/live").json() == {"status": "ok"}
    assert client.get("/api/v1/health/ready").json() == {"status": "ready", "mode": "rules"}


def test_direct_idn_url_contract(client):
    text = " https://예시.한국/공지 "
    response = client.post("/api/v1/analyses", json={"input_type": "url", "content": text})
    assert response.status_code == 200
    body = response.json()
    assert body["risk_level"] == "insufficient_information"
    assert body["evidence"] == [] and body["confidence"] is None
    assert body["input_assessment"]["status"] == "url_only"
    assert body["urls"][0]["ascii_host"] == "xn--vv4b11d.xn--3e0b707e"
    reputation = body["urls"][0]["reputation"]
    assert reputation["status"] == "not_connected" and reputation["reason"] == "key_missing"
    assert reputation["provider"] is None and reputation["checked_at"] is None
    assert reputation["full_hash_verified"] is False and reputation["threat_types"] == []
    assert body["analysis_stages"][2]["status"] == "not_connected"
    occurrence = body["urls"][0]["occurrences"][0]
    assert text[occurrence["start"]:occurrence["end"]] == occurrence["text"]


@pytest.mark.parametrize("content", ["ftp://e.invalid/", "example.invalid", "https://-bad.invalid/", "https://a.invalid https://b.invalid"])
def test_direct_url_invalid_is_sanitized_error(client, content, caplog):
    response = client.post("/api/v1/analyses", json={"input_type": "url", "content": content})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "INVALID_URL"
    assert content not in response.text + caplog.text


def test_mixed_valid_invalid_and_duplicate_url_contract(client):
    response = client.post("/api/v1/analyses", json={"input_type": "text", "content": "https://E.invalid:443/ https://e.invalid/ https://-bad.invalid/"})
    assert response.status_code == 200
    body = response.json()
    assert len(body["urls"]) == 2
    assert len(body["urls"][0]["occurrences"]) == 2
    assert body["urls"][1]["validation_status"] == "invalid"
    assert body["urls"][1]["reputation"]["status"] == "not_requested"
    assert body["risk_level"] == "insufficient_information"


def test_too_many_unique_urls_is_not_silently_truncated(client):
    response = client.post("/api/v1/analyses", json={"input_type": "text", "content": " ".join(f"https://e.invalid/{n}" for n in range(11))})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "TOO_MANY_URLS"
