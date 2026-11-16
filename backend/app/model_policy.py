"""규칙 결과와 문장 전체 점수 신호의 임시 종합 (rules-model-dev-v2, 팀 확정 필요).

- 모델 신호(점수가 임계값 이상)는 판정을 올릴 수만 있다: 정보 부족 → 의심. 의심·위험은 유지하고 내리지 않는다.
- v2: 정상(normal)은 아래 조건을 모두 만족할 때만 반환한다 (normal_eligible + 모델 점수가 정상 임계값 미만).
  규칙에 걸리지 않았다는 것만으로는 정상이 아니다. 의심·위험을 정상으로 내리는 경로는 없다.
- 점수는 응답에 넣지 않는다. 원문 구절 근거가 아니므로 evidence에 넣지 않는다. 정상도 안전 보증이 아니다.
"""

from typing import Literal

from .contracts import RiskLevel
from .rule_templates import HEADINGS

# clear: 점수가 정상 임계값 미만(교차검증에서 어떤 사기 문자의 점수보다도 낮은 구간). 정상 임계값이 없는 모델은 clear를 내지 않는다.
ModelOutcome = Literal["flagged", "not_flagged", "clear", "not_configured", "load_failed", "timeout", "error", "not_applicable"]
NORMAL_REASON = "NO_RISK_SIGNAL_FOUND"
# 머리말만 있는 안내문은 위험 신호가 없는 것으로 본다. 그 밖의 근거(긴급성·불이익, 명의 주장, 가족 호칭 등)가 하나라도 있으면 정상이 아니다.
NORMAL_ALLOWED_RULE_IDS = frozenset({"impersonation-header-v1"})
NORMAL_ACTIONS = ["지금은 따로 조치하지 않아도 돼요. 다만 돈·인증번호·개인정보를 요구하는 연락이 이어지면 다시 확인해 보세요.",
                  "확실하지 않다면 직접 확인한 공식 연락처로 확인하세요."]

MODEL_SIGNAL_EXPLANATION = "문장 전체가 사기 문자에서 자주 보이는 표현과 비슷해요. 어떤 부분 때문인지는 알 수 없고, 사기라고 확정한 것은 아니에요."
BASE_LIMITATION = "규칙 기반 개발 버전: 결과는 안전을 보장하지 않아요."
# 화면에 보이는 문장이라 내부 용어 대신 쉬운 말로 쓴다.
MODEL_LIMITATIONS: dict[ModelOutcome, str] = {
    "flagged": "문장 전체 비교는 참고용이에요. 어떤 부분 때문인지 알려주지 않고, 잘못 경고할 수 있어요.",
    "not_flagged": "문장 전체 비교에서 따로 눈에 띈 점은 없었어요. 그렇다고 안전한 메시지라는 뜻은 아니에요.",
    "clear": "문장 전체 비교에서도 사기 문자와 비슷한 점을 찾지 못했어요. 그렇다고 안전을 보증하는 것은 아니에요.",
    "not_configured": "문장 전체 비교 기능이 꺼져 있어 규칙 결과만 보여드려요.",
    "load_failed": "문장 전체 비교 기능을 준비하지 못해 규칙 결과만 보여드려요.",
    "timeout": "문장 전체 비교가 제때 끝나지 않아 규칙 결과만 보여드려요.",
    "error": "문장 전체 비교 중 문제가 생겨 규칙 결과만 보여드려요.",
    "not_applicable": "주소만 입력해서 문장 전체 비교는 하지 않았어요.",
}
STAGE_STATUS: dict[ModelOutcome, str] = {
    "flagged": "completed", "not_flagged": "completed", "clear": "completed", "not_configured": "not_connected",
    "load_failed": "unavailable", "timeout": "unavailable", "error": "unavailable", "not_applicable": "not_applicable",
}


def normal_eligible(level: RiskLevel, input_status: str, rule_ids: set[str], has_urls: bool, reputation_stage: str) -> bool:
    """모델 결과를 보기 전의 정상 후보 조건. 하나라도 어긋나면 정상을 반환하지 않는다.

    - 규칙 결과가 정보 부족이고(의심·위험은 내리지 않는다), 문장 형태의 충분한 입력이다.
    - 규칙 근거가 없거나 대괄호 머리말뿐이다.
    - 주소가 없거나, 주소가 있으면 평판 조회를 실제로 마쳤다. 조회하지 못한 주소가 있는 문자는 정상이라고 하지 않는다.
      (조회 결과 없음을 정상의 근거로 쓰는 것이 아니다. 근거는 문장이고, 확인하지 못한 주소가 정상 판정을 막을 뿐이다.)
    """
    return (level == RiskLevel.INSUFFICIENT_INFORMATION and input_status == "sentence_present"
            and rule_ids <= NORMAL_ALLOWED_RULE_IDS and (not has_urls or reputation_stage == "completed"))


def combine_model(level: RiskLevel, reason: str, explanation: str, outcome: ModelOutcome,
                  eligible_for_normal: bool = False) -> tuple[RiskLevel, str, str]:
    if outcome == "clear" and eligible_for_normal and level == RiskLevel.INSUFFICIENT_INFORMATION:
        rest = explanation.removeprefix(HEADINGS[RiskLevel.INSUFFICIENT_INFORMATION]).strip()
        return RiskLevel.NORMAL, NORMAL_REASON, " ".join(filter(None, [HEADINGS[RiskLevel.NORMAL], rest]))
    if outcome != "flagged":
        return level, reason, explanation
    if level == RiskLevel.INSUFFICIENT_INFORMATION:
        # 정보 부족 머리말("규칙만으로 판단하기 어려워요")을 모델 신호 문장으로 바꾸고 규칙 설명은 남긴다.
        heading = HEADINGS[RiskLevel.INSUFFICIENT_INFORMATION]
        rest = explanation.removeprefix(heading).strip()
        return RiskLevel.SUSPICIOUS, "MODEL_SIGNAL_ONLY", " ".join(filter(None, [MODEL_SIGNAL_EXPLANATION, rest]))
    return level, reason, f"{explanation} {MODEL_SIGNAL_EXPLANATION}"
