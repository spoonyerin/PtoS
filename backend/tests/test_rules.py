import asyncio
import socket

import pytest

from app.analyzers import RuleBasedAnalyzer
from app.contracts import AnalysisInput, FactorCode as F
from app.rule_detection import ACTION_CODES


def analyze(text):
    return asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(input_type="text", content=text)))


@pytest.mark.parametrize("text", [
    "내일 오후 2시에 동네 도서관에서 만나요.",
    "은행입니다. 다음 주 월요일은 휴무입니다.",
    "은행은 인증번호를 요구하지 않습니다.",
    "인증번호를 알려주지 마세요.",
    "돈을 송금하지 마세요. 링크를 클릭하지 마세요. 앱을 설치하지 마세요.",
    "개인정보를 보내지 마세요. 앱 설치가 필요 없습니다.",
    "인증번호를 알려주지 말고 점심시간을 알려주세요.",
    "인증번호가 아니라 모임 장소를 알려주세요.",
    "인증번호를 알려주면 안 됩니다.",
    "돈을 보내줘야 하는 것은 아닙니다.",
    "피싱 예방 교육입니다. 인증번호를 알려달라는 문자는 거절하세요.",
    '"은행입니다. 인증번호를 알려주세요."는 피싱 사기 예시입니다.',
    '사기 예시: “앱을 설치해주세요.” 실제로 따라하지 마세요.',
    "인증번호를 알려주세요라는 문자는 피싱입니다.",
    '"인증번호를 알려주세요"라고 요구하지 않습니다.',
    '“송금해주세요”라고 요청하지 마세요.',
    "피싱 예방 교육입니다. 은행이 인증번호를 보내라고 한다면 거절하세요.",
    "긴급", "인증번호", "은행 인증번호 긴급", "그거 지금 처리", "https://example.invalid/path",
])
def test_no_unconfirmed_action_and_never_normal(text):
    result = analyze(text)
    assert result.risk_level == "insufficient_information"
    assert not {e.factor_code for e in result.evidence} & ACTION_CODES
    assert result.confidence is None
    assert result.is_demo is False
    assert result.analysis_mode == "rules"
    assert result.analysis_stages[1].status == "not_implemented"


@pytest.mark.parametrize("text,code", [
    ("인증번호를 알려주세요.", F.CREDENTIAL_REQUEST),
    ("주민등록번호를 입력하세요.", F.CREDENTIAL_REQUEST),
    ("개인 정보를 보내 주세요.", F.CREDENTIAL_REQUEST),
    ("OTP를 전달해주세요.", F.CREDENTIAL_REQUEST),
    ("계좌번호를 보내줘.", F.CREDENTIAL_REQUEST),
    ("돈을 보내주세요.", F.MONEY_REQUEST),
    ("100만 원을 입금해주세요.", F.MONEY_REQUEST),
    ("수수료를 납부하세요.", F.MONEY_REQUEST),
    ("링크를 눌러주세요.", F.LINK_CLICK),
    ("https://example.invalid/test 에 접속하세요.", F.LINK_CLICK),
    ("앱을 설치해주세요.", F.APP_INSTALL),
    ("원격 지원 프로그램을 실행하세요.", F.APP_INSTALL),
])
def test_individual_request_is_suspicious_not_dangerous(text, code):
    result = analyze(text)
    assert result.risk_level == "suspicious"
    assert code in {e.factor_code for e in result.evidence}
    assert result.input_assessment.status == "action_identified"
    assert result.policy_reason == "ACTIONABLE_SIGNAL"


@pytest.mark.parametrize("text,codes,reason", [
    ("은행 담당자입니다. 인증번호를 알려주세요.", {F.IMPERSONATION, F.CREDENTIAL_REQUEST}, "COMBINED_IDENTITY_REQUEST"),
    ("엄마 나 딸이야. 돈을 보내줘.", {F.IMPERSONATION, F.MONEY_REQUEST}, "COMBINED_IDENTITY_REQUEST"),
    ("경찰입니다. 앱을 설치해주세요.", {F.IMPERSONATION, F.APP_INSTALL}, "COMBINED_IDENTITY_REQUEST"),
    ("지금 바로 돈을 보내주세요. 인증번호를 알려주세요.", {F.URGENCY_THREAT, F.MONEY_REQUEST, F.CREDENTIAL_REQUEST}, "COMBINED_MONEY_REQUEST"),
    ("즉시 링크를 눌러주세요. 인증번호를 입력하세요.", {F.URGENCY_THREAT, F.LINK_CLICK, F.CREDENTIAL_REQUEST}, "COMBINED_URGENT_CREDENTIAL_LINK"),
    ("은행입니다.\n인증번호를 알려주세요.", {F.IMPERSONATION, F.CREDENTIAL_REQUEST}, "COMBINED_IDENTITY_REQUEST"),
    ('"은행입니다. 인증번호를 알려주세요."', {F.IMPERSONATION, F.CREDENTIAL_REQUEST}, "COMBINED_IDENTITY_REQUEST"),
    ("은행입니다. 피싱 예방을 위해 인증번호를 보내주세요.", {F.IMPERSONATION, F.CREDENTIAL_REQUEST}, "COMBINED_IDENTITY_REQUEST"),
    ('“인증번호를 알려주세요”는 사기 예시입니다. 은행입니다. 실제 인증번호를 보내주세요.', {F.IMPERSONATION, F.CREDENTIAL_REQUEST}, "COMBINED_IDENTITY_REQUEST"),
])
def test_only_defined_combinations_raise_warning(text, codes, reason):
    result = analyze(text)
    assert result.risk_level == "dangerous"
    assert codes <= {e.factor_code for e in result.evidence}
    assert result.policy_reason == reason


def test_separate_paragraphs_do_not_combine():
    result = analyze("은행입니다. 휴무 안내입니다.\n\n인증번호를 알려주세요.")
    assert result.risk_level == "suspicious"


def test_negated_request_does_not_hide_separate_affirmative_request():
    result = analyze("인증번호를 알려주지 마세요. 하지만 돈을 보내주세요.")
    assert result.risk_level == "suspicious"
    assert {e.factor_code for e in result.evidence} == {F.MONEY_REQUEST}
    assert "인증번호" not in result.explanation


def test_negated_threat_does_not_inflate_an_unrelated_request():
    result = analyze("계좌 정지가 아닙니다. 링크를 눌러주세요. 인증번호를 알려주세요.")
    assert result.risk_level == "suspicious"
    assert F.URGENCY_THREAT not in {e.factor_code for e in result.evidence}


def test_education_quote_is_excluded_without_hiding_new_demand():
    result = analyze('“은행입니다. 인증번호를 알려주세요.”는 사기 예시입니다. 앱을 설치해주세요.')
    assert result.risk_level == "suspicious"
    assert {e.factor_code for e in result.evidence} == {F.APP_INSTALL}


def test_sufficiency_distinguishes_fragment_sentence_and_short_demand():
    assert analyze("그거").input_assessment.status == "fragment"
    assert analyze("도서관은 내일 휴무입니다.").input_assessment.status == "sentence_present"
    assert analyze("OTP를 알려줘").input_assessment.status == "action_identified"


def test_exact_unicode_evidence_and_template_alignment():
    text = "😀 은행 담당자입니다.\n인증 번호를 알려 주세요. 앱을 설치해주세요."
    result = analyze(text)
    assert result.risk_level == "dangerous"
    for e in result.evidence:
        assert e.snippet == text[e.start:e.end]
        assert e.start < e.end
        assert e.source == "rule" and e.rule_id
        assert e.label in result.risk_factors
    assert any(e.snippet == "인증 번호를 알려 주세요" for e in result.evidence)
    assert "설치" in result.explanation
    assert "링크" not in result.explanation + " ".join(result.action_guidance)
    assert len(result.action_guidance) == len(set(result.action_guidance))


def test_url_is_never_opened_or_treated_as_reputation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("Network access is forbidden")
    monkeypatch.setattr(socket, "create_connection", forbidden)
    result = analyze("https://example.invalid/unknown")
    assert result.risk_level == "insufficient_information"
    assert result.analysis_stages[2].status == "not_connected"
    assert analyze("도서관 휴무입니다.").analysis_stages[2].status == "not_applicable"


def test_repeated_signals_do_not_inflate_policy_or_duplicate_actions():
    result = analyze("인증번호를 알려주세요. 인증번호를 알려주세요. 인증번호를 알려주세요.")
    assert result.risk_level == "suspicious"
    assert len(result.evidence) == 3
    assert len(result.risk_factors) == len(result.action_guidance) == 1
