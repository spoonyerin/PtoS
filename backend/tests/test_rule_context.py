import asyncio

import pytest

from app.analyzers import RuleBasedAnalyzer
from app.contracts import AnalysisInput


def analyze(text, kind="text"):
    return asyncio.run(RuleBasedAnalyzer().analyze(AnalysisInput(
        input_type=kind, content=text, ocr_confirmed=True if kind == "ocr_text" else None)))


@pytest.mark.parametrize("kind", ["text", "ocr_text"])
@pytest.mark.parametrize("separator", [" ", "\n", "\n\n", "\r\n\r\n", "\n \t\n\n"])
def test_user_message_is_consistent_across_line_wrapping(kind, separator):
    text = f"은행 담당자입니다.{separator}인증번호를 알려주세요. https://example.invalid/corrected 지금 바로 확인해주세요."
    result = analyze(text, kind)
    assert result.risk_level == "dangerous"
    assert result.policy_reason == "COMBINED_IDENTITY_REQUEST"
    assert result.analysis_version == "rules-reputation-dev-v2" and result.confidence is None
    assert result.urls[0].reputation.status == "not_connected"
    for evidence in result.evidence:
        assert text[evidence.start:evidence.end] == evidence.snippet


@pytest.mark.parametrize("text", [
    "은행입니다.\n\n돈을 보내주세요.",
    "경찰입니다.\n\n앱을 설치해주세요.",
    "은행입니다.\n\n지금 바로 인증번호를 알려주세요.",
    "은행입니다.\n\n인증번호를 알려주세요. 😀",  # 코드포인트 좌표 유지
])
def test_only_adjacent_identity_intro_and_direct_request_bridge(text):
    result = analyze(text)
    assert result.risk_level == "dangerous"
    assert any("도입 문단" in reason for reason in result.input_assessment.reasons)
    for evidence in result.evidence:
        assert text[evidence.start:evidence.end] == evidence.snippet


@pytest.mark.parametrize("text", [
    "은행입니다. 휴무 안내입니다.\n\n인증번호를 알려주세요.",
    "은행입니다.\n\n다른 사람이 보낸 내용입니다.\n\n인증번호를 알려주세요.",
    "은행입니다.\n\n다른 화자는 인증번호를 알려주세요.",
    "돈을 보내주세요.\n\n인증번호를 알려주세요.",
    "은행입니다.\n\n피싱 예방을 위해 인증번호를 보내주세요.",
    '"은행입니다."\n\n인증번호를 알려주세요.',
    '은행입니다.\n\n"인증번호를 알려주세요."',
    '은행입니다.\n\n"인증번호를 알려주세요."는 사기 예시입니다. 앱을 설치해주세요.',
])
def test_unconfirmed_cross_paragraph_relationship_is_not_promoted(text):
    assert analyze(text).risk_level == "suspicious"


@pytest.mark.parametrize("separator", [" ", "\n", "\n\n", "\r\n\r\n"])
@pytest.mark.parametrize("left,right", [
    ("상담원: 은행 담당자입니다.", "사용자: 인증번호를 알려주세요."),
    ("A: 은행 담당자입니다.", "B: 인증번호를 알려주세요."),
    ("[은행] [오후 2:00] 은행 담당자입니다.", "[다른 사람] [오후 2:01] 인증번호를 알려주세요."),
    ("은행 담당자입니다.", "---\n인증번호를 알려주세요."),
    ("은행 담당자입니다.", "> 인증번호를 알려주세요."),
])
def test_explicit_speakers_and_message_markers_block_combination(separator, left, right):
    assert analyze(left + separator + right).risk_level == "suspicious"


@pytest.mark.parametrize("text", [
    '은행입니다.\n\n"인증번호를 알려주세요."는 사기 예시입니다.',
    '"은행입니다.\n\n인증번호를 알려주세요."는 사기 예시입니다.',
    "은행입니다.\n\n인증번호를 요구하지 않습니다.",
    "은행입니다.\n\n인증번호를 알려주지 마세요.",
])
def test_education_and_negation_do_not_supply_bridge_evidence(text):
    assert analyze(text).risk_level == "insufficient_information"


def test_url_content_does_not_act_as_a_speaker_or_education_marker():
    text = "은행입니다.\n\n인증번호를 알려주세요. https://e.invalid/사기예시/A:B"
    assert analyze(text).risk_level == "dangerous"
