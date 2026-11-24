"""rules-dev-v8(임시): 정상 인증번호 안내 예외 확장의 회귀 검증.

1) 번호가 대상어 앞에 오는 형식("[123456] 본인확인 인증번호")도 "번호를 직접 보여 줌"으로 본다.
2) 공유 금지 경고가 없어도 짧고, 요구가 "입력"뿐이며, 주소·제3자·교육 인용이 없으면 예외를 적용한다.
모든 문장은 직접 지은 예시이며 평가셋 문장이 아니다. 탐지 성능 검증이 아니다.
"""

import asyncio

import pytest

from app.analyzers import RuleBasedAnalyzer
from app.contracts import AnalysisInput, FactorCode as F

INPUT_ONLY_REASON = "인증번호를 직접 보여 주고 링크 없이 화면에 입력하라는 짧은 안내라 입력 요구로 채택하지 않았어요."
WARNED_REASON = "인증번호를 직접 보여 주고 타인 공유를 경고하는 안내라 입력 요구로 채택하지 않았어요."


def analyze(text):
    return asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(input_type="text", content=text)))


def codes(result):
    return {e.factor_code for e in result.evidence}


def assert_spans(text, result):
    for e in result.evidence:
        assert e.snippet == text[e.start:e.end] and e.start < e.end


# 번호가 대상어 앞에 오는 형식 + 공유 금지 경고(기존 E 조건) → 예외.
@pytest.mark.parametrize("text", [
    "[가상몰] [583920] 본인확인 인증번호를 입력하세요. 타인과 공유하지 마세요.",
    "본인 확인을 위해 [인증번호] 인증번호를 입력하세요. 보안을 위해 공유하지 마세요.",
    "[가상페이] 583920 인증번호를 입력해 주세요. 다른 사람에게 알려주지 마세요.",
])
def test_code_before_target_with_warning(text):
    result = analyze(text)
    assert F.CREDENTIAL_REQUEST not in codes(result)
    assert result.risk_level.value == "insufficient_information"
    assert any(r.startswith(WARNED_REASON) for r in result.input_assessment.reasons)


# 공유 금지 경고 없는 짧은 입력 안내 → v8 예외.
@pytest.mark.parametrize("text", [
    "[가상통신] 인증번호[인증번호]를 정확히 입력해주세요.",
    "[583920] 본인확인 인증번호를 입력하세요! [가상결제]",
    "[가상서비스] 가입을 계속하시려면 화면에 인증번호 [인증번호]를 입력해 주세요.",
])
def test_short_input_only_notice_without_warning(text):
    result = analyze(text)
    assert F.CREDENTIAL_REQUEST not in codes(result)
    assert result.risk_level.value == "insufficient_information"
    assert any(r.startswith(INPUT_ONLY_REASON) for r in result.input_assessment.reasons)


# 계속 경고해야 하는 문장(흉내 포함). 예외가 적용되지 않아 민감정보 요구 근거가 남는다.
@pytest.mark.parametrize("text", [
    # 번호를 보여 주며 알려 달라고 한다.
    "[가상은행] 인증번호 [인증번호]를 알려주세요.",
    "[583920] 인증번호를 회신해 주세요.",
    # 번호 + 입력 + 주소.
    "[가상은행] 인증번호 [인증번호]를 입력하세요. http://example.invalid/a",
    # 번호를 보여 주지 않는다.
    "[가상은행] 인증번호를 입력하세요.",
    # 대괄호 머리말은 번호가 아니다.
    "[가상은행] 본인확인 인증번호를 입력하세요.",
    # 제3자·다른 경로 언급.
    "[가상은행] 인증번호 [인증번호]를 입력해 주세요. 상담원이 곧 전화로 확인합니다.",
    # 다른 민감정보.
    "[가상은행] 비밀번호와 인증번호 [인증번호]를 입력하세요.",
    # 긴 문자 속 입력 요구(짧은 안내 조건 밖, 공유 금지 경고도 없음).
    "[가상은행] 고객님의 계정 보호를 위해 새 기기 등록 절차를 진행하고 있습니다. 등록을 마치려면 인증번호 [인증번호]를 입력해 주세요. "
    "등록이 끝나면 기존 기기에서는 다시 로그인해야 합니다.",
])
def test_not_exempted(text):
    result = analyze(text)
    assert F.CREDENTIAL_REQUEST in codes(result)
    assert result.risk_level.value in {"suspicious", "dangerous"}
    assert not any(r.startswith(INPUT_ONLY_REASON) for r in result.input_assessment.reasons)
    assert_spans(text, result)


# 긴급·불이익 근거가 있으면 예외가 아니다(위험 조합이 남을 수 있다).
def test_urgency_blocks_input_only_exception():
    result = analyze("[가상은행] 오늘 안에 인증번호 [인증번호]를 입력하세요.")
    assert F.CREDENTIAL_REQUEST in codes(result)
    assert result.risk_level.value in {"suspicious", "dangerous"}


# 공유 금지 경고가 교육 인용 안에만 있으면 v8 짧은 안내 예외도 적용하지 않는다.
def test_quoted_warning_does_not_enable_input_only_exception():
    text = "[가상은행] 인증번호 [인증번호]를 입력바랍니다. '타인에게 알려주지 마세요'라는 안내는 피싱 예방 교육 문구예요."
    result = analyze(text)
    assert F.CREDENTIAL_REQUEST in codes(result)
    assert result.risk_level.value == "suspicious"


# 알려진 한계(현재 판정 기록용): 번호를 괄호로 보여 주는 형식("인증번호(583920)")은 E·v8 모두 "번호를 보여 줌"으로
# 보지 않아 경고 없는 입력 안내가 suspicious로 남는다. 바꾸면 이 기대값을 함께 고친다.
def test_known_limitation_parenthesized_code():
    result = analyze("[가상게임] 본인확인 인증번호(583920)를 입력해 주세요.")
    assert F.CREDENTIAL_REQUEST in codes(result)
    assert result.risk_level.value == "suspicious"


# 예외가 적용돼도 정상(normal)은 아니다. 규칙만으로는 정보 부족이다.
def test_exception_never_returns_normal_from_rules():
    result = analyze("[가상통신] 인증번호[인증번호]를 정확히 입력해주세요.")
    assert result.risk_level.value == "insufficient_information"
