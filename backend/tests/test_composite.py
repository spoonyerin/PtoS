"""CompositeAnalyzer 종합 흐름. 모두 가짜 모델이며 실제 모델 성능 검증이 아니다."""

import asyncio
import logging
import time

import pytest
from fastapi.testclient import TestClient

from app.analyzers import CompositeAnalyzer, RuleBasedAnalyzer
from app.contracts import AnalysisInput, RiskLevel
from app.main import create_app
from app.model_adapter import URL_PLACEHOLDER, ModelState
from app.model_policy import BASE_LIMITATION, MODEL_LIMITATIONS, MODEL_SIGNAL_EXPLANATION
from app.rule_templates import HEADINGS
from app.url_reputation import DisconnectedReputationProvider

DANGEROUS = "은행입니다. 인증번호를 알려주세요."
SUSPICIOUS = "앱을 설치해주세요."
INSUFFICIENT = "도서관은 내일 휴무입니다."
DEFAULT_ACTIONS = ["보낸 사람과 요구하는 행동, 앞뒤 내용을 확인해주세요.", "확실하지 않다면 직접 확인한 공식 연락처로 확인하세요."]


class FakeModel:
    version = "fake-v1"
    threshold = 0.5

    def __init__(self, score=0.0, delay=0.0, error=False):
        self._score, self.delay, self.error = score, delay, error
        self.calls: list[str] = []

    def score(self, text):
        self.calls.append(text)
        if self.delay:
            time.sleep(self.delay)
        if self.error:
            raise RuntimeError(f"failed on {text}")
        return self._score


def rules():
    return RuleBasedAnalyzer(DisconnectedReputationProvider("test"))


def run(state, text, input_type="text", timeout=1.0):
    analyzer = CompositeAnalyzer(rules(), state, timeout)
    return asyncio.run(analyzer.analyze(AnalysisInput(input_type=input_type, content=text)))


def rules_only(text, input_type="text"):
    return asyncio.run(rules().analyze(AnalysisInput(input_type=input_type, content=text)))


def loaded(model):
    return ModelState("loaded", model)


@pytest.mark.parametrize("text,score,level,reason", [
    (INSUFFICIENT, 0.9, "suspicious", "MODEL_SIGNAL_ONLY"),
    (INSUFFICIENT, 0.5, "suspicious", "MODEL_SIGNAL_ONLY"),
    (INSUFFICIENT, 0.1, "insufficient_information", "ANALYSIS_INCOMPLETE"),
    (SUSPICIOUS, 0.9, "suspicious", "ACTIONABLE_SIGNAL"),
    (SUSPICIOUS, 0.1, "suspicious", "ACTIONABLE_SIGNAL"),
    (DANGEROUS, 0.9, "dangerous", "COMBINED_IDENTITY_REQUEST"),
    (DANGEROUS, 0.0, "dangerous", "COMBINED_IDENTITY_REQUEST"),
])
def test_model_only_raises_insufficient_to_suspicious(text, score, level, reason):
    model = FakeModel(score)
    result = run(loaded(model), text)
    base = rules_only(text)
    assert (result.risk_level, result.policy_reason) == (level, reason)
    # 규칙에 걸려도 모델을 생략하지 않는다.
    assert model.calls == [text]
    assert result.risk_level != RiskLevel.NORMAL and result.confidence is None
    assert result.analysis_mode == "rules" and result.is_demo is False
    assert result.evidence == base.evidence and result.risk_factors == base.risk_factors
    assert result.action_guidance == base.action_guidance
    assert result.analysis_stages[1].status == "completed"
    assert result.analysis_version == "rules-model-dev-v1"
    flagged = score >= model.threshold
    assert (MODEL_SIGNAL_EXPLANATION in result.explanation) is flagged
    assert result.limitations[:2] == [BASE_LIMITATION, MODEL_LIMITATIONS["flagged" if flagged else "not_flagged"]]
    assert not any("경량 모델" in line or "학습" in line for line in [result.explanation, *result.limitations])


def test_model_signal_only_uses_model_sentence_and_default_actions():
    result = run(loaded(FakeModel(0.9)), INSUFFICIENT)
    assert result.explanation == MODEL_SIGNAL_EXPLANATION
    assert result.action_guidance == DEFAULT_ACTIONS
    assert result.evidence == [] and result.risk_factors == []


def test_model_signal_keeps_weak_rule_explanation_when_raising():
    # 명의 주장만 있는 문장은 규칙상 정보 부족이며 그 설명은 남는다.
    text = "은행입니다. 다음 주 월요일은 휴무입니다."
    base = rules_only(text)
    assert base.risk_level == "insufficient_information" and base.evidence
    result = run(loaded(FakeModel(0.9)), text)
    assert result.risk_level == "suspicious"
    assert result.explanation.startswith(MODEL_SIGNAL_EXPLANATION)
    assert "규칙만으로 판단하기 어려워요" not in result.explanation
    rule_sentences = base.explanation.removeprefix(HEADINGS[RiskLevel.INSUFFICIENT_INFORMATION]).strip()
    assert rule_sentences and result.explanation == f"{MODEL_SIGNAL_EXPLANATION} {rule_sentences}"


@pytest.mark.parametrize("state,outcome,stage", [
    (ModelState("not_configured"), "not_configured", "not_connected"),
    (ModelState("load_failed", reason="MODEL_SHA256_MISMATCH"), "load_failed", "unavailable"),
    (loaded(FakeModel(0.9, delay=0.3)), "timeout", "unavailable"),
    (loaded(FakeModel(0.9, error=True)), "error", "unavailable"),
])
@pytest.mark.parametrize("text", [DANGEROUS, SUSPICIOUS, INSUFFICIENT])
def test_model_failure_keeps_rule_result(state, outcome, stage, text, caplog):
    with caplog.at_level(logging.DEBUG):
        result = run(state, text, timeout=0.05)
    base = rules_only(text)
    assert (result.risk_level, result.policy_reason, result.evidence) == (base.risk_level, base.policy_reason, base.evidence)
    assert result.explanation == base.explanation and result.action_guidance == base.action_guidance
    assert result.analysis_stages[1].status == stage
    assert [s.name for s in result.analysis_stages] == [s.name for s in base.analysis_stages]
    assert result.analysis_stages[2] == base.analysis_stages[2]
    assert result.limitations[:2] == [BASE_LIMITATION, MODEL_LIMITATIONS[outcome]]
    assert text not in caplog.text


def test_url_input_does_not_call_model():
    model = FakeModel(0.9)
    url = "https://example.invalid/path"
    result = run(loaded(model), url, input_type="url")
    assert model.calls == []
    assert result.analysis_stages[1].status == "not_applicable"
    assert result.risk_level == rules_only(url, "url").risk_level
    assert MODEL_LIMITATIONS["not_applicable"] in result.limitations


def test_model_receives_text_with_urls_replaced():
    model = FakeModel(0.1)
    text = "확인하세요 https://example.invalid/a 감사합니다"
    run(loaded(model), text)
    assert model.calls == [f"확인하세요 {URL_PLACEHOLDER} 감사합니다"]


def test_ocr_text_uses_model():
    model = FakeModel(0.9)
    result = asyncio.run(CompositeAnalyzer(rules(), loaded(model)).analyze(
        AnalysisInput(input_type="ocr_text", content=INSUFFICIENT, ocr_confirmed=True)))
    assert model.calls == [INSUFFICIENT] and result.risk_level == "suspicious"


def test_api_loads_model_once_and_slow_model_is_not_504():
    loads = []

    def loader():
        loads.append(1)
        return loaded(FakeModel(0.9, delay=0.3))

    with TestClient(create_app(model_loader=loader, model_timeout=0.05)) as client:
        for _ in range(2):
            response = client.post("/api/v1/analyses", json={"input_type": "text", "content": DANGEROUS})
            assert response.status_code == 200
            body = response.json()
            assert body["risk_level"] == "dangerous"
            assert body["analysis_stages"][1] == {"name": "lightweight_model", "status": "unavailable"}
            assert "score" not in response.text
    assert loads == [1]


def test_api_model_signal_only_response():
    with TestClient(create_app(model_loader=lambda: loaded(FakeModel(0.9)))) as client:
        body = client.post("/api/v1/analyses", json={"input_type": "text", "content": INSUFFICIENT}).json()
    assert body["risk_level"] == "suspicious" and body["policy_reason"] == "MODEL_SIGNAL_ONLY"
    assert body["confidence"] is None and body["evidence"] == []
    assert body["analysis_stages"][1] == {"name": "lightweight_model", "status": "completed"}
