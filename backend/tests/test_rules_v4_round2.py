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


# 알려진 한계(현재 판정 기록용): 정상 인증번호·로그인 안내도 민감정보 "입력" 요구로 보아 suspicious가 된다.
# 규칙은 발신처가 공식인지, 사용자가 직접 요청한 인증인지 알 수 없다. 정책을 바꾸면 이 기대값을 함께 고친다.
# 1·3번은 2차 A(입력바랍니다형·조건형)부터 suspicious, 2·5번은 그 전부터 suspicious였다. 4번은 요구가 없어 정보 부족.
@pytest.mark.parametrize("text,level,rule_id", [
    ("[가상서비스] 인증번호 [인증번호]를 입력바랍니다. 타인에게 알려주지 마세요.", "suspicious", "credential_request-v1"),
    ("[가상서비스] 본인 확인을 위해 인증번호 [인증번호]를 입력해 주세요.", "suspicious", "credential_request-v1"),
    ("비밀번호를 입력해야 로그인이 가능합니다.", "suspicious", "credential_request-required-v1"),
    ("[가상서비스] 인증번호는 [인증번호]입니다. 타인에게 알려주지 마세요.", "insufficient_information", None),
    ("로그인하려면 비밀번호를 입력하세요.", "suspicious", "credential_request-v1"),
])
def test_known_limitation_legit_otp_and_login_notices(text, level, rule_id):
    result = analyze(text)
    assert result.risk_level.value == level
    assert rule_ids(result, F.CREDENTIAL_REQUEST) == ({rule_id} if rule_id else set())


# --- B-1: 송금·입금·이체·선입금 요구의 활용형 ---

@pytest.mark.parametrize("text,rule_id", [
    ("보증금은 내 계좌로 이체바랍니다.", "money_request-v1"),
    ("행사 참가비는 오늘까지 송금 요망.", "money_request-v1"),
    ("친구야 그 돈 오늘 안에 입금해.", "money_request-v1"),
    ("가입 확정 전에 선입금이 필요합니다.", "money_request-required-v1"),
    ("수수료를 선입금하시면 바로 지급됩니다.", "money_request-required-v1"),
])
def test_money_request_forms(text, rule_id):
    result = analyze(text)
    assert rule_id in rule_ids(result, F.MONEY_REQUEST)
    assert result.risk_level.value in {"suspicious", "dangerous"}
    assert_spans(text, result)


def test_money_form_with_identity_is_dangerous():
    text = "가상은행 고객센터입니다. 보호 조치를 위해 안전계좌로 이체바랍니다."
    result = analyze(text)
    assert F.MONEY_REQUEST in {e.factor_code for e in result.evidence}
    assert result.policy_reason == "COMBINED_IDENTITY_REQUEST"
    assert_spans(text, result)


@pytest.mark.parametrize("text", [
    "지난번에 송금해서 고마워.",
    "용돈은 내가 이미 입금해 놨어.",
    "벌써 이체해?",
    "저희는 선입금을 요구하지 않습니다.",
    "이 상품은 선입금이 필요 없습니다.",
    "선입금은 필요하지 않습니다.",
    "'선입금이 필요합니다'라는 문자는 사기예요.",
    "선입금하면 수익을 준다는 말은 사기입니다.",
    "급여가 오늘 입금되었습니다.",
])
def test_money_forms_negative(text):
    assert F.MONEY_REQUEST not in {e.factor_code for e in analyze(text).evidence}


# 알려진 한계(현재 판정 기록용): 정상 회비·모임비 안내의 "입금 바랍니다"도 금전 요구로 보아 suspicious가 된다.
# 받는 계좌가 정상인지 규칙은 알 수 없다. 정책을 바꾸면 이 기대값을 함께 고친다.
@pytest.mark.parametrize("text", [
    "이번 달 동호회 회비는 총무 계좌로 입금 바랍니다.",
])
def test_known_limitation_legit_dues_notice(text):
    result = analyze(text)
    assert result.risk_level.value == "suspicious"
    assert rule_ids(result, F.MONEY_REQUEST) == {"money_request-v1"}


def test_credential_form_spans_with_crlf_and_emoji():
    text = "🔒 [가상은행]\r\n😀 카드번호를 입력바랍니다."
    result = analyze(text)
    evidence = [e for e in result.evidence if e.factor_code == F.CREDENTIAL_REQUEST]
    assert evidence and evidence[0].snippet == "카드번호를 입력바랍니다"
    assert_spans(text, result)
