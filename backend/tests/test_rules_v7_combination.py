"""rules-dev-v7(임시): 명의(약한 명의 포함) + 불이익 예고 + 민감정보를 넘기라는 요구의 회귀 검증.

모든 문장은 직접 지은 예시이며 평가셋 문장이 아니다. 탐지 성능 검증이 아니다.
"""

import asyncio

import pytest

from app.analyzers import RuleBasedAnalyzer
from app.contracts import AnalysisInput, FactorCode as F

REASON = "COMBINED_IDENTITY_PENALTY_HANDOVER"


def analyze(text):
    return asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(input_type="text", content=text)))


@pytest.mark.parametrize("text", [
    "[국민은행] 계좌가 정지될 예정입니다. 지금 바로 인증번호와 계좌번호를 회신해 주세요.",
    "[한빛카드] 미납 대금이 있습니다. 카드번호를 알려주세요.",
    "[새봄통신] 요금 연체로 회선이 정지될 예정입니다. 주민등록번호를 전송해 주세요.",
    "엄마 나야. 내 계좌가 정지될 예정이래. 인증번호 좀 알려줘.",
])
def test_identity_penalty_and_handover_request_is_dangerous(text):
    result = analyze(text)
    assert (result.risk_level, result.policy_reason) == ("dangerous", REASON)
    codes = {e.factor_code for e in result.evidence}
    assert {F.IMPERSONATION, F.URGENCY_THREAT, F.CREDENTIAL_REQUEST} <= codes
    for e in result.evidence:
        assert e.snippet == text[e.start:e.end]


@pytest.mark.parametrize("text", [
    # 화면에 입력하라는 안내형은 넘기라는 요구가 아니다: 의심에 둔다.
    "[한빛카드] 3분 안에 입력하지 않으면 결제가 취소됩니다. 인증번호를 입력해 주세요.",
    "[새봄은행] 장기 미사용 계좌는 거래가 제한될 예정입니다. 앱에서 비밀번호를 입력해 주세요.",
    # 불이익 예고가 없으면 약한 명의 + 민감정보 요구는 그대로 의심이다.
    "[한빛카드] 본인 확인을 위해 인증번호를 회신해 주세요.",
    "[국민은행] 지금 바로 인증번호를 회신해 주세요.",
    # 명의가 없으면 그대로 의심이다.
    "계좌가 정지될 예정입니다. 인증번호를 회신해 주세요.",
])
def test_narrower_cases_stay_suspicious(text):
    result = analyze(text)
    assert result.risk_level == "suspicious" and result.policy_reason != REASON


@pytest.mark.parametrize("text", [
    "[한빛카드] 미납 대금이 있습니다. 인증번호는 누구에게도 알려주지 마세요.",
    "[국민은행] 계좌가 정지될 예정입니다. 가까운 영업점에 문의해 주세요.",
])
def test_no_handover_request_is_not_dangerous(text):
    assert analyze(text).risk_level != "dangerous"


def test_signals_in_separate_messages_do_not_combine():
    text = "[국민은행] 계좌가 정지될 예정입니다.\n\n친구: 인증번호를 알려주세요."
    assert analyze(text).policy_reason != REASON
