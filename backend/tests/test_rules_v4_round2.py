"""rules-dev-v4 2차 보강(임시)의 회귀 검증. 모든 문장은 직접 지은 예시이며 평가셋 문장이 아니다. 탐지 성능 검증이 아니다."""

import asyncio

import pytest

from app.analyzers import RuleBasedAnalyzer
from app.contracts import AnalysisInput, FactorCode as F


def analyze(text):
    return asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(input_type="text", content=text)))


def rule_ids(result, code):
    return {e.rule_id for e in result.evidence if e.factor_code == code}


def assert_spans(text, result):
    for e in result.evidence:
        assert e.snippet == text[e.start:e.end] and e.start < e.end


# --- A: 민감정보 요구 동사의 활용형 ---

@pytest.mark.parametrize("text,rule_id", [
    ("[가상은행] 보안 점검을 위해 카드번호를 입력바랍니다.", "credential_request-v1"),
    ("새 단말기 등록을 위해 OTP를 회신 바랍니다.", "credential_request-v1"),
    ("적립금 지급을 위해 계좌번호를 인증하세요.", "credential_request-v1"),
    ("잠긴 계정은 비밀번호를 입력해 잠금을 해제하세요.", "credential_request-chain-v1"),
    ("보안카드 번호를 회신하셔야 출금 제한이 해제됩니다.", "credential_request-required-v1"),
    ("주민등록번호를 입력해야 신청이 가능합니다.", "credential_request-required-v1"),
])
def test_credential_request_forms(text, rule_id):
    result = analyze(text)
    assert rule_id in rule_ids(result, F.CREDENTIAL_REQUEST)
    assert result.risk_level.value == "suspicious"
    assert_spans(text, result)


def test_credential_info_target_with_identity_is_dangerous():
    text = "가상은행 고객센터입니다. 본인 확인용 인증정보를 전달하세요."
    result = analyze(text)
    assert F.CREDENTIAL_REQUEST in {e.factor_code for e in result.evidence}
    assert result.policy_reason == "COMBINED_IDENTITY_REQUEST"
    assert_spans(text, result)


@pytest.mark.parametrize("text", [
    "인증번호를 타인에게 알려주지 마세요.",
    "비밀번호를 입력해 봤는데 안 돼요.",
    "비밀번호를 입력해 저장하지 않도록 하세요.",
    "카드번호를 입력해야 하는 것은 아닙니다.",
    "비밀번호는 회신하셔야 할 필요가 없습니다.",
    "'카드번호를 입력바랍니다'라는 문자는 사기입니다.",
    "OTP를 회신 바랍니다라는 문자는 피싱이에요.",
    "어제 받은 인증번호로 로그인했어요.",
])
def test_credential_forms_negative(text):
    assert F.CREDENTIAL_REQUEST not in {e.factor_code for e in analyze(text).evidence}


def test_credential_form_spans_with_crlf_and_emoji():
    text = "🔒 [가상은행]\r\n😀 카드번호를 입력바랍니다."
    result = analyze(text)
    evidence = [e for e in result.evidence if e.factor_code == F.CREDENTIAL_REQUEST]
    assert evidence and evidence[0].snippet == "카드번호를 입력바랍니다"
    assert_spans(text, result)
