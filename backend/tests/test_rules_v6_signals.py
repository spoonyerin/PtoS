"""rules-dev-v6(임시): 연락 유도·혜택·비밀 유지 신호의 회귀 검증.

모든 문장은 직접 지은 예시이며 평가셋 문장이 아니다. 탐지 성능 검증이 아니다.
"""

import asyncio

import pytest

from app.analyzers import RuleBasedAnalyzer
from app.contracts import AnalysisInput, FactorCode as F


def analyze(text):
    return asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(input_type="text", content=text)))


def ids(result, code=None):
    return {e.rule_id for e in result.evidence if code is None or e.factor_code == code}


def assert_spans(text, result):
    for e in result.evidence:
        assert e.snippet == text[e.start:e.end] and e.start < e.end


# --- 결제·승인 통지 + 문자 속 번호로 전화 유도 → 의심 ---

@pytest.mark.parametrize("text", [
    "[국제발신]\n해외승인 398,000원\n본인 아닐 시 문의: 02-123-4567",
    "가상페이 결제완료 568,000원 문의 [전화번호]",
    "본인이 아니라면 1588-1234 로 신고 바랍니다. 해외결제 USD 302 승인",
    "가상카드 승인 1,250,000원(일시불)\r\n본인 아닐 경우 고객상담: 0212345678",
], ids=["overseas", "paid-masked", "number-first", "crlf"])
def test_payment_notice_with_callback_number_is_suspicious(text):
    result = analyze(text)
    assert (result.risk_level, result.policy_reason) == ("suspicious", "UNEXPECTED_PAYMENT_CALLBACK")
    assert "contact_request-payment-callback-v1" in ids(result, F.CONTACT_REQUEST)
    assert result.input_assessment.status == "action_identified"
    assert "실제 결제가 있었는지 확인한 것은 아니에요" in result.explanation
    assert any("공식 앱" in action for action in result.action_guidance)
    assert_spans(text, result)


@pytest.mark.parametrize("text", [
    "[가상병원] 내일 오후 2시 예약입니다. 문의: 02-123-4567",          # 평범한 문의 번호 안내
    "택배가 오늘 도착합니다. 기사 연락처 010-1234-5678",
    "가상카드 승인 12,000원 일시불 05/17 가상마트",                     # 전화 유도 없는 승인 알림
    "본인 아닐 시 고객센터로 문의해 주세요.",                           # 번호 없음
], ids=["clinic", "courier", "approval-only", "no-number"])
def test_callback_or_payment_alone_does_not_raise_the_level(text):
    result = analyze(text)
    assert result.risk_level == "insufficient_information"
    assert "contact_request-payment-callback-v1" not in ids(result)


def test_plain_inquiry_number_is_a_weak_signal_only():
    result = analyze("[가상병원] 내일 오후 2시 예약입니다. 문의: 02-123-4567")
    assert ids(result, F.CONTACT_REQUEST) == {"contact_request-callback-v1"}
    assert "이 표현만으로 위험하다고 판단하지 않아요" in result.explanation


# --- 혜택·당첨 ---

@pytest.mark.parametrize("text,reason", [
    ("이벤트에 당첨되셨습니다. 수수료 5만원을 입금해 주세요.", "COMBINED_BENEFIT_REQUEST"),
    ("무료 쿠폰 당첨! 수령을 위해 카드번호를 입력해 주세요.", "COMBINED_BENEFIT_REQUEST"),
])
def test_benefit_with_money_or_credential_request_is_dangerous(text, reason):
    result = analyze(text)
    assert (result.risk_level, result.policy_reason) == ("dangerous", reason)
    assert F.BENEFIT_LURE in {e.factor_code for e in result.evidence}
    assert_spans(text, result)


def test_benefit_with_pressure_and_url_is_suspicious():
    text = "미수령 환급금이 있습니다. 기한이 지나면 소멸됩니다 http://example.invalid/a"
    result = analyze(text)
    assert (result.risk_level, result.policy_reason) == ("suspicious", "BENEFIT_PRESSURE_LINK")
    assert "실제 혜택이 있는지 확인한 것은 아니에요" in result.explanation


@pytest.mark.parametrize("text", [
    "지난달 이벤트 당첨자를 발표했습니다. 축하드립니다.",                       # 혜택 언급만
    "청년 지원금 신청 안내입니다. 자세한 내용은 주민센터에서 확인할 수 있습니다.",   # 주소 없음
    "환급금이 내일 등록하신 계좌로 입금될 예정입니다.",                          # 압박·주소 없음
])
def test_benefit_mention_alone_does_not_raise_the_level(text):
    result = analyze(text)
    assert result.risk_level == "insufficient_information"
    assert ids(result, F.BENEFIT_LURE) == {"benefit_lure-v1"}


def test_benefit_in_an_educational_quote_is_ignored():
    result = analyze("“당첨되셨습니다. 수수료를 입금해 주세요”라는 문자는 사기 예시입니다.")
    assert result.risk_level == "insufficient_information" and not ids(result, F.BENEFIT_LURE)


# --- 비밀 유지 요구 ---

@pytest.mark.parametrize("text", [
    "엄마한테는 말하지 말고 50만원만 보내줘.",
    "이 일은 비밀로 해 주시고 인증번호를 알려주세요.",
])
def test_secrecy_with_money_or_credential_request_is_dangerous(text):
    result = analyze(text)
    assert (result.risk_level, result.policy_reason) == ("dangerous", "COMBINED_SECRECY_REQUEST")
    assert ids(result, F.SECRECY_REQUEST) == {"secrecy_request-v1"}
    assert any("가족이나 믿을 수 있는 사람" in action for action in result.action_guidance)
    assert_spans(text, result)


def test_secrecy_alone_is_a_weak_signal():
    result = analyze("생일 선물이니까 아빠한테는 비밀로 해줘.")
    assert result.risk_level == "insufficient_information" and ids(result, F.SECRECY_REQUEST)


@pytest.mark.parametrize("text", [
    "인증번호는 [482913]입니다. 다른 사람에게 알리지 마세요.",
    "비밀번호는 가족에게도 말하지 마세요.",
    "개인정보는 누구에게도 알리지 않습니다.",
])
def test_security_advice_about_codes_is_not_a_secrecy_request(text):
    assert not ids(analyze(text), F.SECRECY_REQUEST)


# --- 가족 연락 요청 근거의 코드 이동 ---

def test_family_contact_evidence_uses_the_contact_code():
    result = analyze("엄마 나 폰 고장나서 수리 맡겼어. 이 번호로 문자 줘")
    assert (result.risk_level, result.policy_reason) == ("suspicious", "FAMILY_DEVICE_CONTACT")
    assert ids(result, F.CONTACT_REQUEST) == {"contact_request-family-v1"}
    assert "contact_request-family-v1" not in ids(result, F.IMPERSONATION)


def test_new_labels_are_listed_as_risk_factors():
    result = analyze("가상페이 결제완료 568,000원 문의 [전화번호]")
    assert "전화·답장 등 연락 유도" in result.risk_factors
