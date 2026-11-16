"""rules-dev-v4 임시 보강의 회귀 검증. 모든 문장은 직접 지은 예시이며 평가셋 문장이 아니다. 탐지 성능 검증이 아니다."""

import asyncio

import pytest

from app.analyzers import RuleBasedAnalyzer
from app.contracts import AnalysisInput, FactorCode as F


def analyze(text):
    return asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(input_type="text", content=text)))


def codes(result):
    return {e.factor_code for e in result.evidence}


def assert_spans(text, result):
    for e in result.evidence:
        assert e.snippet == text[e.start:e.end] and e.start < e.end


# --- 후보 5: 관계 자기소개(아들·딸·친구)는 구절 첫머리에서만 강한 명의 ---

@pytest.mark.parametrize("text,snippet", [
    ("아들이야. 급하게 50만 원만 보내줘.", "아들이야"),
    ("어머니, 저 막내딸인데 수수료 좀 보내 주세요.", "딸인데"),
    ("[Web발신] 친구인데 상품권 좀 사 줄래?", "친구인데"),
    ("안녕 엄마 나 큰아들인데 인증번호 좀 알려줘.", "아들인데"),
])
def test_kin_self_intro_at_clause_start_is_strong_identity(text, snippet):
    result = analyze(text)
    assert any(e.factor_code == F.IMPERSONATION and e.snippet == snippet for e in result.evidence)
    assert result.policy_reason == "COMBINED_IDENTITY_REQUEST"
    assert_spans(text, result)


@pytest.mark.parametrize("text", [
    "제 딸이 다니는 학원 선생님 친구인데요, 수강료 30만 원을 입금해 주세요.",
    "부장님 아들입니다만 회비 5만 원을 보내 주세요.",
    "그 사람은 사장님 친구입니다. 인증번호를 알려주세요.",
    "우리 동네 약국 주인 딸이야? 앱을 설치하세요.",
])
def test_kin_word_mid_clause_is_not_identity_claim(text):
    result = analyze(text)
    assert F.IMPERSONATION not in codes(result)
    assert result.risk_level == "suspicious"
    assert_spans(text, result)


def test_kin_intro_paragraph_still_bridges_to_next_request():
    result = analyze("딸이야.\n\n돈 좀 보내줘.")
    assert result.policy_reason == "COMBINED_IDENTITY_REQUEST"


def test_parent_call_with_kin_keeps_existing_strong_identity():
    result = analyze("아빠 저 아들입니다. 계좌번호 알려주세요.")
    assert result.policy_reason == "COMBINED_IDENTITY_REQUEST"


# --- 후보 4: 부정은 표현에 바로 이어지는 서술어(첫 연결 어미까지)에만 적용 ---

def urgency_rules(result):
    return {e.rule_id for e in result.evidence if e.factor_code == F.URGENCY_THREAT}


@pytest.mark.parametrize("text,expected_rules", [
    ("고객님 계좌가 즉시 해지되니 무시하지 마세요.", {"urgency_threat-v1", "urgency_threat-penalty-v1"}),
    ("오늘 자정까지 확인하지 않으면 이용이 정지됩니다.", {"urgency_threat-deadline-v1", "urgency_threat-penalty-v1"}),
    ("지금 바로 납부하지 않을 경우 압류 예정이니 미루지 마세요.", {"urgency_threat-v1", "urgency_threat-penalty-v1"}),
    ("내일 자정 이용이 제한될 예정이며 다시 안내하지 않습니다.", {"urgency_threat-deadline-v1", "urgency_threat-penalty-v1"}),
])
def test_negation_in_later_predicate_keeps_urgency_and_penalty(text, expected_rules):
    result = analyze(text)
    assert expected_rules <= urgency_rules(result)
    assert result.risk_level == "insufficient_information"  # 압박 표현만으로 판정을 올리지 않는다.
    assert_spans(text, result)


def test_identity_ending_with_connective_is_not_negated_by_later_clause():
    text = "택배 기사인데요 문 앞에 두지 말라고 하셔서 연락드려요. 배송비 3,000원을 입금해 주세요."
    result = analyze(text)
    assert any(e.factor_code == F.IMPERSONATION and e.snippet == "택배 기사인데요" for e in result.evidence)
    assert result.policy_reason == "COMBINED_IDENTITY_REQUEST"
    assert_spans(text, result)


@pytest.mark.parametrize("text", [
    "계좌가 정지되지 않습니다.",
    "서비스가 즉시 중단되지 않으니 안심하세요.",
    "긴급한 일은 아니에요.",
    "오늘 자정까지 처리할 필요가 없습니다.",
    "거래가 정지된 것이 아니니 걱정하지 마세요.",
])
def test_true_negation_still_removes_urgency(text):
    result = analyze(text)
    assert F.URGENCY_THREAT not in codes(result)


def test_conditional_negation_does_not_create_action_request():
    # 조건형 부정 처리는 압박 표현에만 적용한다. 요구 동사의 부정 판단은 바뀌지 않는다.
    result = analyze("지금 바로 확인하지 않으면 인증번호를 알려주지 마세요.")
    assert F.CREDENTIAL_REQUEST not in codes(result)


def test_immediately_is_not_conditional_si():
    # "즉시 해지되니"의 '시'를 조건("미확인 시 해지")으로 잡아 근거가 겹쳐 사라지지 않게 한다.
    text = "즉시 해지될 예정입니다."
    result = analyze(text)
    snippets = {e.snippet for e in result.evidence if e.factor_code == F.URGENCY_THREAT}
    assert {"즉시", "해지"} <= snippets
    assert_spans(text, result)


def test_conditional_si_penalty_still_detected():
    result = analyze("미확인 시 자동 해지됩니다.")
    assert "urgency_threat-penalty-v1" in urgency_rules(result)


# --- 후보 4 보완: 청구어 바로 뒤 첫 서술어가 "없다·아니다"이면 불이익 근거로 채택하지 않음 ---

def penalty_evidence(result):
    return [e for e in result.evidence if e.rule_id == "urgency_threat-penalty-v1"]


@pytest.mark.parametrize("text", [
    "이번 달 미납 금액이 없습니다.",
    "연체 내역이 없고 정상 처리되었습니다.",
    "과태료 부과 대상이 아니고 별도 조치는 필요 없어요.",
])
def test_claim_word_followed_by_absence_is_not_penalty(text):
    result = analyze(text)
    assert not penalty_evidence(result)
    assert F.URGENCY_THREAT not in codes(result)


def test_no_claim_notice_with_header_deadline_link_is_not_rule_a():
    text = "[OO카드] 이번 달 미납 금액이 없습니다. 오늘 자정까지 상세 내역 확인: http://example.test/a"
    result = analyze(text)
    assert not penalty_evidence(result)
    assert result.risk_level != "dangerous"
    assert result.policy_reason != "COMBINED_NOTICE_PENALTY_DEADLINE"
    assert_spans(text, result)


def test_claim_word_with_existing_charge_keeps_penalty():
    text = "미납 요금이 있습니다. 오늘 자정까지 납부하지 않으면 이용이 정지됩니다."
    result = analyze(text)
    assert any(e.snippet == "미납" for e in penalty_evidence(result))
    assert any(e.snippet == "정지" for e in penalty_evidence(result))
    assert_spans(text, result)
