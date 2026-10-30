"""규칙 결과와 문장 전체 점수 신호의 임시 종합 (rules-model-dev-v1, 팀 확정 필요).

모델 신호는 판정을 올릴 수만 있다: 정보 부족 → 의심. 의심·위험은 유지하고 내리지 않는다.
normal은 반환하지 않고, 점수는 응답에 넣지 않는다. 원문 구절 근거가 아니므로 evidence에 넣지 않는다.
"""

from typing import Literal

from .contracts import RiskLevel
from .rule_templates import HEADINGS

ModelOutcome = Literal["flagged", "not_flagged", "not_configured", "load_failed", "timeout", "error", "not_applicable"]

MODEL_SIGNAL_EXPLANATION = "문장 전체가 사기 문자에서 자주 보이는 표현과 비슷해요. 어떤 부분 때문인지는 알 수 없고, 사기라고 확정한 것은 아니에요."
BASE_LIMITATION = "규칙 기반 개발 버전: 결과는 안전을 보장하지 않아요."
# 화면에 보이는 문장이라 내부 용어 대신 쉬운 말로 쓴다.
MODEL_LIMITATIONS: dict[ModelOutcome, str] = {
    "flagged": "문장 전체 비교는 참고용이에요. 어떤 부분 때문인지 알려주지 않고, 잘못 경고할 수 있어요.",
    "not_flagged": "문장 전체 비교에서 따로 눈에 띈 점은 없었어요. 그렇다고 안전한 메시지라는 뜻은 아니에요.",
    "not_configured": "문장 전체 비교 기능이 꺼져 있어 규칙 결과만 보여드려요.",
    "load_failed": "문장 전체 비교 기능을 준비하지 못해 규칙 결과만 보여드려요.",
    "timeout": "문장 전체 비교가 제때 끝나지 않아 규칙 결과만 보여드려요.",
    "error": "문장 전체 비교 중 문제가 생겨 규칙 결과만 보여드려요.",
    "not_applicable": "주소만 입력해서 문장 전체 비교는 하지 않았어요.",
}
STAGE_STATUS: dict[ModelOutcome, str] = {
    "flagged": "completed", "not_flagged": "completed", "not_configured": "not_connected",
    "load_failed": "unavailable", "timeout": "unavailable", "error": "unavailable", "not_applicable": "not_applicable",
}


def combine_model(level: RiskLevel, reason: str, explanation: str, outcome: ModelOutcome) -> tuple[RiskLevel, str, str]:
    if outcome != "flagged":
        return level, reason, explanation
    if level == RiskLevel.INSUFFICIENT_INFORMATION:
        # 정보 부족 머리말("규칙만으로 판단하기 어려워요")을 모델 신호 문장으로 바꾸고 규칙 설명은 남긴다.
        heading = HEADINGS[RiskLevel.INSUFFICIENT_INFORMATION]
        rest = explanation.removeprefix(heading).strip()
        return RiskLevel.SUSPICIOUS, "MODEL_SIGNAL_ONLY", " ".join(filter(None, [MODEL_SIGNAL_EXPLANATION, rest]))
    return level, reason, f"{explanation} {MODEL_SIGNAL_EXPLANATION}"
