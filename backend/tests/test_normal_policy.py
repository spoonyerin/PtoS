"""정상(normal) 반환 정책(rules-model-dev-v2, 임시)의 회귀 검증. 가짜 모델과 직접 지은 문장만 쓴다. 탐지 성능 검증이 아니다."""

import asyncio
import json

import pytest

from app.analyzers import CompositeAnalyzer, RuleBasedAnalyzer
from app.contracts import AnalysisInput, RiskLevel, UrlReputation
from app.model_adapter import MODEL_PATH_ENV, ModelState, load_configured_model
from app.model_policy import MODEL_LIMITATIONS, NORMAL_ACTIONS, NORMAL_REASON, combine_model, normal_eligible
from app.rule_templates import HEADINGS
from evaluation.model_training import choose_normal_threshold, normal_counts, train
from test_model_training import write_csv

PLAIN = "이번 주 토요일 모임은 공원에서 열립니다."
HEADER_ONLY = "[가상택배] 주문하신 상품이 오늘 배송될 예정입니다."


class FakeModel:
    version = "fake-v1"

    def __init__(self, score, threshold=0.7, normal_threshold=0.3):
        self._score, self.threshold, self.normal_threshold = score, threshold, normal_threshold

    def score(self, text):
        return self._score


class FixedReputation:
    def __init__(self, status):
        self.status = status

    async def lookup(self, url):
        return UrlReputation(status=self.status, provider="fake")


def analyze(text, score=0.1, input_type="text", reputation=None, **model_kwargs):
    rules = RuleBasedAnalyzer(FixedReputation(reputation) if reputation else None)
    analyzer = CompositeAnalyzer(rules, ModelState("loaded", FakeModel(score, **model_kwargs)))
    return asyncio.run(analyzer.analyze(AnalysisInput(input_type=input_type, content=text)))


def test_plain_sentence_with_a_clear_model_score_is_normal_without_claiming_safety():
    result = analyze(PLAIN)
    assert result.risk_level == "normal" and result.policy_reason == NORMAL_REASON
    assert result.explanation == HEADINGS[RiskLevel.NORMAL] and "보증하는 것은 아니에요" in result.explanation
    assert result.action_guidance == NORMAL_ACTIONS and result.evidence == [] and result.confidence is None
    assert MODEL_LIMITATIONS["clear"] in result.limitations
    assert [stage.status for stage in result.analysis_stages] == ["completed", "completed", "not_applicable", "not_applicable", "not_connected"]


def test_header_only_notice_can_be_normal_and_keeps_its_evidence_and_guidance():
    result = analyze(HEADER_ONLY)
    assert result.risk_level == "normal"
    assert [e.rule_id for e in result.evidence] == ["impersonation-header-v1"]
    assert result.explanation.startswith(HEADINGS[RiskLevel.NORMAL]) and "머리말" in result.explanation
    assert result.action_guidance != NORMAL_ACTIONS and any("공식" in action for action in result.action_guidance)


@pytest.mark.parametrize("score,level,reason", [
    (0.29, "normal", NORMAL_REASON),
    (0.3, "insufficient_information", "ANALYSIS_INCOMPLETE"),   # 정상 임계값과 같으면 정상이 아니다
    (0.5, "insufficient_information", "ANALYSIS_INCOMPLETE"),
    (0.7, "suspicious", "MODEL_SIGNAL_ONLY"),
])
def test_model_score_bands(score, level, reason):
    result = analyze(PLAIN, score)
    assert (result.risk_level, result.policy_reason) == (level, reason)


@pytest.mark.parametrize("text", [
    "가상은행 담당자입니다. 내일 다시 연락드리겠습니다.",            # 명의 주장
    "[가상은행] 고객님의 계좌가 정지될 예정입니다.",                # 불이익 표현
    "지금 바로 확인이 필요한 안내입니다.",                        # 긴급성 표현
    "엄마 나 폰 고장났어. 내일 집에 갈게요.",                     # 가족 호칭
    "도서관 모임 공원 토요일",                                  # 단편 입력
], ids=["identity", "penalty", "urgency", "family", "fragment"])
def test_weak_signals_or_fragments_are_never_normal(text):
    assert analyze(text, 0.0).risk_level == "insufficient_information"


@pytest.mark.parametrize("text,level", [
    ("은행 담당자입니다. 인증번호를 알려주세요.", "dangerous"),
    ("앱을 설치해주세요.", "suspicious"),
])
def test_clear_model_score_never_lowers_a_warning(text, level):
    assert analyze(text, 0.0).risk_level == level


def test_message_with_an_unchecked_url_is_not_normal():
    text = "이번 주 모임 장소는 아래에서 볼 수 있습니다. http://example.invalid/a 모임은 토요일에 열립니다."
    assert analyze(text, 0.0).risk_level == "insufficient_information"                         # 평판 미연결
    assert analyze(text, 0.0, reputation="timeout").risk_level == "insufficient_information"   # 조회 실패
    checked = analyze(text, 0.0, reputation="unknown")                                          # 조회를 마쳤고 일치 없음
    assert checked.risk_level == "normal" and any("안전 판정이 아니며" in item for item in checked.limitations)


def test_direct_url_input_is_never_normal():
    assert analyze("http://example.invalid/a", 0.0, "url", reputation="unknown").risk_level == "insufficient_information"


@pytest.mark.parametrize("state", [ModelState("not_configured"), ModelState("load_failed", reason="MODEL_LOAD_ERROR")])
def test_without_a_working_model_nothing_is_normal(state):
    result = asyncio.run(CompositeAnalyzer(RuleBasedAnalyzer(), state).analyze(AnalysisInput(input_type="text", content=PLAIN)))
    assert result.risk_level == "insufficient_information"
    assert asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(input_type="text", content=PLAIN))).risk_level == "insufficient_information"


def test_model_without_a_normal_threshold_never_returns_normal():
    assert analyze(PLAIN, 0.0, normal_threshold=None).risk_level == "insufficient_information"


def test_eligibility_and_combination_rules():
    insufficient = RiskLevel.INSUFFICIENT_INFORMATION
    assert normal_eligible(insufficient, "sentence_present", set(), False, "not_applicable")
    assert normal_eligible(insufficient, "sentence_present", {"impersonation-header-v1"}, True, "completed")
    assert not normal_eligible(insufficient, "sentence_present", set(), True, "not_connected")
    assert not normal_eligible(insufficient, "sentence_present", {"urgency_threat-v1"}, False, "not_applicable")
    assert not normal_eligible(insufficient, "fragment", set(), False, "not_applicable")
    assert not normal_eligible(RiskLevel.SUSPICIOUS, "sentence_present", set(), False, "not_applicable")
    assert combine_model(insufficient, "R", "설명", "clear", False) == (insufficient, "R", "설명")
    assert combine_model(insufficient, "R", "설명", "not_flagged", True) == (insufficient, "R", "설명")
    assert combine_model(RiskLevel.SUSPICIOUS, "R", "설명", "clear", True) == (RiskLevel.SUSPICIOUS, "R", "설명")


@pytest.mark.parametrize("scores,labels,threshold,expected", [
    ([0.9, 0.6, 0.4, 0.2, 0.1], [1, 1, 1, 0, 0], 0.6, 0.4),      # 사기 점수 최솟값
    ([0.9, 0.5, 0.6, 0.55], [1, 1, 0, 0], 0.9, None),            # 그보다 낮은 정상 행이 없음
    ([0.9, 0.8, 0.1], [1, 1, 0], 0.5, None),                     # 모델 신호 임계값보다 큼
    ([0.2, 0.1], [0, 0], None, None),                            # 사기 행 없음
])
def test_normal_threshold_keeps_every_fraud_row_out(scores, labels, threshold, expected):
    chosen = choose_normal_threshold(scores, labels, threshold)
    assert chosen == expected
    assert normal_counts(scores, labels, chosen)["scam_below"] == 0


def test_training_records_the_normal_threshold_and_loader_checks_it(tmp_path):
    out = tmp_path / "model"
    manifest = train(write_csv(tmp_path / "eval.csv"), out, seed=7, n_splits=4, model_version="test-v1")
    assert manifest["oof_normal_counts"]["scam_below"] == 0 and "normal_threshold_rule" in manifest
    state = load_configured_model({MODEL_PATH_ENV: str(out)})
    expected = manifest["normal_threshold"] if manifest["normal_threshold_found"] else None
    assert state.status == "loaded" and state.model.normal_threshold == expected
    assert "정상 임계값(임시)" in (out / "train-report.md").read_text(encoding="utf-8")
    # 정상 임계값이 모델 신호 임계값보다 크면 어긋난 manifest로 보고 거부한다.
    path = out / "manifest.json"
    broken = json.loads(path.read_text(encoding="utf-8")) | {"normal_threshold_found": True, "normal_threshold": 0.999}
    broken["threshold"] = 0.5
    path.write_text(json.dumps(broken, ensure_ascii=False), encoding="utf-8")
    assert load_configured_model({MODEL_PATH_ENV: str(out)}).reason == "MANIFEST_INVALID"
    # 정상 임계값이 없는 옛 manifest는 그대로 읽고 정상을 반환하지 않는다.
    old = {k: v for k, v in broken.items() if not k.startswith("normal_threshold")}
    path.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    assert load_configured_model({MODEL_PATH_ENV: str(out)}).model.normal_threshold is None
