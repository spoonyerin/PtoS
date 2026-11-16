"""조건부 추가 검토(LLM)의 호출 조건과 임시 종합 (llm-review-dev-v1, 팀 확정 필요).

- 호출 조건: 규칙 결과가 정보 부족이고 문장 전체 비교도 신호를 내지 않았는데, 판정을 올리지 못한 약한 근거
  (명의 주장, 긴급성·불이익 표현)가 남아 있을 때만. 근거가 서로 어긋나 판단하기 어려운 경우다.
- 이미 의심·위험이면 호출하지 않는다. 추가 검토는 판정을 올릴 수만 있어서 결과가 달라지지 않는다.
- 종합: scam_signs일 때만 정보 부족 → 의심. 내리지 않고, 위험으로 올리지 않고, normal은 반환하지 않는다.
- 설명은 고정 문장이다. 추가 검토가 만든 문장은 쓰지 않으며 원문 구절 근거가 아니므로 evidence에 넣지 않는다.
"""

from typing import Literal

from .contracts import RiskLevel
from .llm_review import LlmReview
from .model_policy import ModelOutcome
from .rule_templates import HEADINGS

# weak_evidence(기본): 약한 근거가 남은 경우만. any_sentence: 문장 형태이기만 하면 호출(비용이 크게 늘어난다).
LlmScope = Literal["weak_evidence", "any_sentence"]
LLM_SIGNAL_EXPLANATION = "글의 흐름이 사기 문자에서 쓰는 수법과 비슷하다는 추가 검토 결과가 있어요. 어떤 부분 때문인지는 알 수 없고, 사기라고 확정한 것은 아니에요."
# 화면에 보이는 문장이라 내부 용어 대신 쉬운 말로 쓴다.
LLM_LIMITATIONS: dict[str, str] = {
    "scam_signs": "추가 검토는 참고용이에요. 어떤 부분 때문인지 알려주지 않고, 잘못 경고할 수 있어요.",
    "no_clear_signs": "추가 검토에서 따로 눈에 띈 점은 없었어요. 그렇다고 안전한 메시지라는 뜻은 아니에요.",
    "timeout": "추가 검토가 제때 끝나지 않아 앞의 결과만 보여드려요.",
    "budget_exhausted": "추가 검토 횟수를 다 써서 앞의 결과만 보여드려요.",
    "failed": "추가 검토를 마치지 못해 앞의 결과만 보여드려요.",
}
SENT_NOTICE = "판단이 어려워 추가 검토를 했어요. 주소·전화번호·긴 숫자를 가린 문장만 외부 서비스로 보냈어요."


def should_review(level: RiskLevel, model_outcome: ModelOutcome, input_status: str, has_weak_evidence: bool,
                  scope: LlmScope = "weak_evidence") -> bool:
    if level != RiskLevel.INSUFFICIENT_INFORMATION or model_outcome in ("flagged", "not_applicable"):
        return False
    if input_status != "sentence_present":
        return False
    return has_weak_evidence or scope == "any_sentence"


def limitation_for(review: LlmReview) -> str:
    if review.status == "completed":
        return LLM_LIMITATIONS[review.judgement]
    return LLM_LIMITATIONS.get(review.status, LLM_LIMITATIONS["failed"])


def combine_llm(level: RiskLevel, reason: str, explanation: str, review: LlmReview) -> tuple[RiskLevel, str, str]:
    if review.status != "completed" or review.judgement != "scam_signs" or level != RiskLevel.INSUFFICIENT_INFORMATION:
        return level, reason, explanation
    heading = HEADINGS[RiskLevel.INSUFFICIENT_INFORMATION]
    rest = explanation.removeprefix(heading).strip()
    return RiskLevel.SUSPICIOUS, "LLM_SIGNAL_ONLY", " ".join(filter(None, [LLM_SIGNAL_EXPLANATION, rest]))
