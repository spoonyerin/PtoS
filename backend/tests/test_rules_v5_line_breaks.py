"""rules-dev-v5(임시): 문장 중간 줄바꿈을 구절 검사에서 이어 보는 처리의 회귀 검증.

모든 문장은 직접 지은 예시이며 평가셋 문장이 아니다. 탐지 성능 검증이 아니다.
"""

import asyncio

import pytest

from app.analyzers import RuleBasedAnalyzer
from app.contracts import AnalysisInput, FactorCode as F


def analyze(text, input_type="text", **kwargs):
    return asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(input_type=input_type, content=text, **kwargs)))


def codes(result):
    return {e.factor_code for e in result.evidence}


def assert_spans(text, result):
    for e in result.evidence:
        assert e.snippet == text[e.start:e.end] and e.start < e.end


@pytest.mark.parametrize("text,level,reason,code", [
    ("은행 담당자입니다. 인증번호를\n알려주세요.", "dangerous", "COMBINED_IDENTITY_REQUEST", F.CREDENTIAL_REQUEST),
    ("은행 담당자입니다. 인증번호를 \r\n  알려주세요.", "dangerous", "COMBINED_IDENTITY_REQUEST", F.CREDENTIAL_REQUEST),
    ("아래 링크를\n눌러주세요 http://example.invalid/a", "suspicious", "ACTIONABLE_SIGNAL", F.LINK_CLICK),
    ("급하게 돈 좀\n보내줄 수 있어?", "suspicious", "ACTIONABLE_SIGNAL", F.MONEY_REQUEST),
    ("원격제어 앱을\n설치해 주세요", "suspicious", "ACTIONABLE_SIGNAL", F.APP_INSTALL),
], ids=["credential", "credential-crlf", "link", "money", "app"])
def test_request_split_by_a_line_break_is_still_found(text, level, reason, code):
    result = analyze(text)
    assert (result.risk_level, result.policy_reason) == (level, reason) and code in codes(result)
    assert_spans(text, result)
    # 근거 구절은 줄바꿈을 포함한 원문 그대로다.
    assert any("\n" in e.snippet for e in result.evidence if e.factor_code == code)


def test_same_result_for_confirmed_ocr_text():
    text = "은행 담당자입니다. 인증번호를\n알려주세요."
    assert analyze(text, "ocr_text", ocr_confirmed=True).risk_level == "dangerous"


@pytest.mark.parametrize("text", [
    "인증번호를\n\n알려주세요",                    # 빈 줄은 그대로 경계
    "인증번호를.\n알려주세요",                     # 문장부호로 끝난 줄
    "인증번호 안내\n1) 알려주세요",                 # 번호 목록
    "인증번호\n- 알려주세요",                      # 기호로 시작하는 줄
    "인증번호\n[안내] 알려주세요",                  # 대괄호 머리말
    "인증번호를 받았어요\n문의: 알려주세요",          # 항목 이름
], ids=["blank-line", "punctuation", "numbered", "bullet", "header", "label"])
def test_other_line_breaks_stay_boundaries(text):
    result = analyze(text)
    assert result.risk_level == "insufficient_information" and F.CREDENTIAL_REQUEST not in codes(result)


def test_negation_split_by_a_line_break_is_recognised():
    result = analyze("인증번호를 절대\n알려주지 마세요")
    assert result.risk_level == "insufficient_information" and F.CREDENTIAL_REQUEST not in codes(result)


def test_negation_on_the_next_line_does_not_erase_urgency_or_identity():
    urgent = analyze("지금 바로 확인하세요\n걱정하지 마세요")
    assert F.URGENCY_THREAT in codes(urgent)
    identity = analyze("은행 담당자입니다\n놀라지 마세요. 인증번호를 알려주세요.")
    assert identity.risk_level == "dangerous"


def test_speaker_labels_on_separate_lines_are_not_joined():
    result = analyze("A: 은행입니다\nB: 인증번호를 알려주세요")
    assert result.risk_level == "suspicious"


def test_line_level_patterns_still_use_the_original_lines():
    # 머리말과 주소 앞 확인 안내는 줄 첫머리·줄 끝 기준 그대로다.
    text = "택배 안내드립니다\n[가상택배] 주소 확인 바랍니다\nhttp://example.invalid/a"
    result = analyze(text)
    assert {e.rule_id for e in result.evidence} >= {"impersonation-header-v1", "link_click-confirm-v1"}
    assert_spans(text, result)
