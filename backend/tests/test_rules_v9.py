"""rules-dev-v9(임시): 새 의심 신호 4가지의 회귀 검증.

1) 안부·재회 표현 + 해외 메신저 아이디 연락 유도 → 의심(MESSENGER_ID_CONTACT)
2) 위반·처벌 통지서 발송 + 주소 → 의심(PENALTY_NOTICE_LINK)
3) 대출·한도 + 자격 조건을 없앤 권유(무직자·소득 증빙 없이 등) → 의심(LOAN_LURE)
4) "6자리 숫자 알려 줘"처럼 숫자를 넘기라는 요구 → 민감정보 요구
모든 문장은 직접 지은 예시이며 평가셋 문장이 아니다. 탐지 성능 검증이 아니다.
"""

import asyncio

import pytest

from app.analyzers import RuleBasedAnalyzer
from app.contracts import AnalysisInput, FactorCode as F


def analyze(text):
    return asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(input_type="text", content=text)))


def rule_ids(result):
    return {e.rule_id for e in result.evidence}


@pytest.mark.parametrize("text", [
    "[국제발신] 오랜만이에요! 번호가 바뀌어서요. 제 LINE: abc1234",
    "친구야 나 기억나? 텔레그램 아이디 tester_77 로 연락 줘",
    "[국제발신] 반가워요 우리 예전에 만나서 얘기했었죠 WeChat: hello88",
])
def test_messenger_id_contact(text):
    result = analyze(text)
    assert result.risk_level.value == "suspicious"
    assert result.policy_reason == "MESSENGER_ID_CONTACT"
    assert "contact_request-messenger-v1" in rule_ids(result)


@pytest.mark.parametrize("text", [
    # 아이디만 있고 안부·재회 표현이나 [국제발신]이 없다.
    "[가상업체] 작업 문의는 카톡 아이디 sample01 로 주세요.",
    "공식 LINE 계정: vshop_official 친구 추가하고 쿠폰 받으세요",
    # 안부만 있고 메신저 아이디가 없다.
    "오랜만이야! 다음 주에 밥 한번 먹자.",
])
def test_messenger_not_raised(text):
    assert "contact_request-messenger-v1" not in rule_ids(analyze(text))


@pytest.mark.parametrize("text", [
    "[가상교통] 신호 위반 과태료 통지서 발송 완료 http://example.invalid/a",
    "[가상구청] 관리법 미준수에 대한 통지서가 전송되었습니다. https://example.invalid/b",
])
def test_penalty_notice_link(text):
    result = analyze(text)
    assert result.risk_level.value == "suspicious"
    assert "urgency_threat-notice-link-v1" in rule_ids(result)


@pytest.mark.parametrize("text", [
    # 주소가 없다.
    "[가상교통] 신호 위반 과태료 통지서가 발송되었습니다. 우편으로 확인해 주세요.",
    # 위반·처벌 없이 결정 통지서 안내만 있다.
    "[가상세무서] 장려금 결정 통지서가 발송되었습니다. https://example.invalid/c",
])
def test_penalty_notice_not_raised(text):
    assert "urgency_threat-notice-link-v1" not in rule_ids(analyze(text))


@pytest.mark.parametrize("text", [
    "(광고) 가상금융 무직자도 최대 한도 3천만원 대출 가능! 상담 문의 주세요.",
    "[가상은행] 소득증빙이 확인되지 않아도 마이너스통장 신청 가능합니다.",
    "고객님은 정책자금 대상자이지만 아직 미신청으로 확인되어 재안내드립니다.",
])
def test_loan_lure(text):
    result = analyze(text)
    assert result.risk_level.value == "suspicious"
    assert "benefit_lure-loan-v1" in rule_ids(result)


@pytest.mark.parametrize("text", [
    # 대출 표현이 없다.
    "무직자 대상 취업 교육 프로그램 안내입니다.",
    # 자격 조건을 없애는 표현이 없다.
    "[가상은행] 주택담보대출 금리 변경 안내입니다. 자세한 내용은 앱에서 확인하세요.",
])
def test_loan_not_raised(text):
    assert "benefit_lure-loan-v1" not in rule_ids(analyze(text))


def test_digits_handover():
    result = analyze("이거 설치하고 화면에 나온 6자리 숫자 알려줘")
    assert F.CREDENTIAL_REQUEST in {e.factor_code for e in result.evidence}
    assert result.risk_level.value == "suspicious"


def test_new_signals_never_dangerous_alone():
    for text in ("[국제발신] 오랜만이에요 제 LINE: abc1234",
                 "(광고) 무직자도 대출 가능합니다."):
        assert analyze(text).risk_level.value == "suspicious"
