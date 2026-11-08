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
