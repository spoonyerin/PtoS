"""rules-dev-v4 3차 보강(임시)의 회귀 검증. 모든 문장은 직접 지은 예시이며 평가셋 문장이 아니다. 탐지 성능 검증이 아니다."""

import asyncio

import pytest

from app.analyzers import RuleBasedAnalyzer
from app.contracts import AnalysisInput, FactorCode as F


def analyze(text):
    return asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(input_type="text", content=text)))


def rule_ids(result, code=None):
    # 연락 요청 근거는 v6에서 CONTACT_REQUEST 코드로 옮겼다. 코드를 주지 않으면 모든 근거의 rule_id를 본다.
    return {e.rule_id for e in result.evidence if code is None or e.factor_code == code}


def assert_spans(text, result):
    for e in result.evidence:
        assert e.snippet == text[e.start:e.end] and e.start < e.end


CONTACT_IDS = {"impersonation-family-device-v1", "contact_request-family-v1"}


# --- 가족·형제 호칭 + 휴대폰 사정 + 답장·메신저 추가 요청 → 의심 ---

@pytest.mark.parametrize("text", [
    "엄마 나 폰 고장나서 수리 맡겼어. 이 번호로 문자 줘",
    "누나 바빠?\n\n핸드폰 액정이 깨져서 수리 맡기고 컴퓨터로 보내는 거야\n\n카톡 추가하고 톡 줘~",
    "오빠\n휴대폰 잃어버렸어 여기로 답장 좀 해줘",
    "[Web발신]\n아빠 전화기가 망가져서 친구 걸로 보내요. 확인하면 연락 주세요",
    "언니 나 폰 떨어뜨려서 수리 맡겼어\r\n새로 만든 계정이야 친구 추가해줘",
], ids=["parent", "sister-paragraphs", "brother", "header-polite", "add-friend-crlf"])
def test_family_device_contact_is_suspicious_not_dangerous(text):
    result = analyze(text)
    assert result.risk_level == "suspicious" and result.policy_reason == "FAMILY_DEVICE_CONTACT"
    ids = rule_ids(result)
    # 휴대폰 사정 구절을 기존 가족 호칭 근거가 이미 잡았으면 같은 구절을 두 번 내지 않는다.
    assert "contact_request-family-v1" in ids and ids & {"impersonation-family-device-v1", "impersonation-family-v1"}
    assert result.input_assessment.status == "action_identified"
    assert "평소와 다른 번호·계정일 수 있어요" in result.explanation
    assert any("직접 전화해 확인" in action for action in result.action_guidance)
    assert_spans(text, result)


@pytest.mark.parametrize("text", [
    "엄마 나 도착했어. 문자 줘",                              # 휴대폰 사정 없음
    "엄마 폰 고장나서 내일 수리 맡길게",                       # 연락 요청 없음
    "폰 고장나서 수리 맡겼어요. 문자 주세요",                   # 가족 호칭 줄 없음
    "엄마가 폰 고장났대. 문자 줘",                            # 부르는 말이 아니라 주어
    "수리 맡기신 휴대폰이 준비되었습니다. 방문 전 연락 주세요",   # 수리점 안내
    "엄마\n오늘 저녁 뭐 먹을지 문자 줘",
], ids=["no-device", "no-contact", "no-kin", "kin-subject", "repair-shop", "plain-family"])
def test_partial_patterns_add_no_evidence(text):
    result = analyze(text)
    assert result.risk_level == "insufficient_information"
    assert not CONTACT_IDS & rule_ids(result)


def test_educational_quote_is_not_a_contact_request():
    text = "“엄마 나 폰 고장나서 수리 맡겼어. 이 번호로 문자 줘”라는 문자는 사기 예시입니다."
    result = analyze(text)
    assert result.risk_level == "insufficient_information" and not CONTACT_IDS & rule_ids(result)


def test_reported_contact_request_is_not_adopted():
    result = analyze("엄마\n폰 고장났다며 문자 줘라는 연락은 피싱이니 조심해")
    assert "contact_request-family-v1" not in rule_ids(result)


def test_existing_combinations_keep_priority_over_contact_rule():
    # 가족 호칭 + 금전 요구 + 링크 요구(규칙 B)는 그대로 위험이고, 금전 요구만 있으면 그대로 ACTIONABLE_SIGNAL이다.
    text = "엄마 나 폰 고장나서 수리 맡겼어. 이 번호로 문자 줘. 급해서 그런데 돈 좀 보내줘. 아래 링크 눌러줘 http://example.invalid/a"
    result = analyze(text)
    assert result.risk_level == "dangerous" and result.policy_reason == "COMBINED_FAMILY_MONEY_LINK"
    money_only = analyze("엄마 나 폰 고장나서 수리 맡겼어. 이 번호로 문자 줘. 급해서 그런데 돈 좀 보내줘.")
    assert money_only.risk_level == "suspicious" and money_only.policy_reason == "ACTIONABLE_SIGNAL"


def test_contact_evidence_is_weak_identity_only():
    # 연락 요청 근거는 명의 조합 1(명시적 명의 + 민감정보)의 명의로 치지 않는다.
    result = analyze("누나\n폰 고장나서 수리 맡겼어 카톡 추가해줘\n인증번호 알려줘")
    assert result.risk_level == "suspicious"


# --- "확인 부탁합니다" + 주소 (확인 계열 링크 요구의 활용형) ---

@pytest.mark.parametrize("text", [
    "가상택배 주소 확인 부탁합니다 http://example.invalid/a",
    "배송 정보 확인부탁해요\nhttp://example.invalid/b",
])
def test_confirm_request_variants_before_url(text):
    result = analyze(text)
    assert result.risk_level == "suspicious"
    assert "link_click-confirm-v1" in rule_ids(result, F.LINK_CLICK)
    assert_spans(text, result)


def test_confirm_request_without_url_is_not_a_link_request():
    result = analyze("내일 회의 자료 확인 부탁합니다.")
    assert result.risk_level == "insufficient_information" and not rule_ids(result, F.LINK_CLICK)
