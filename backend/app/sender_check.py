"""발신 번호 확인 (sender-check-dev-v1, 임시, 팀 확정 필요).

사용자가 직접 적은 보낸 번호를 문자가 내세운 기관 이름과 비교한다. **불일치만 판정을 올린다.**

- 번호가 등록된 번호와 같아도 판정을 낮추지 않고 정상의 근거로 쓰지 않는다. 발신 번호는 바꿔서 표시할 수 있다.
- 비교 대상은 규칙이 찾은 기관 명의 표현(대괄호 머리말, "○○은행입니다")뿐이다. 가족·지인 호칭은 비교하지 않는다.
- 보낸 번호는 원문 구절이 아니므로 근거 좌표는 문자 안의 기관 이름 구절을 가리킨다.
- 번호는 로그·파일·캐시에 남기지 않고 외부로 보내지 않는다.
- 공식 번호 목록은 저장소에 두지 않는다. 사람이 확인해 만든 JSON 파일을 환경 변수로 지정할 때만 쓴다.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from .contracts import Evidence, FactorCode, RiskLevel
from .rule_detection import Finding
from .rule_templates import HEADINGS

PATH_ENV = "PTOS_OFFICIAL_NUMBERS_PATH"
MAX_LIST_BYTES = 1_048_576
LABEL = "보낸 번호와 내세운 이름 불일치"
REASON = "SENDER_MISMATCH"
RULE_LIST = "sender_mismatch-official-list-v1"
RULE_TYPE = "sender_mismatch-number-type-v1"

# 번호 형태만으로 비교하는 대상: 금융·공공기관 이름. 택배 기사·보험 설계사·매장처럼 개인 휴대전화로 연락하는 일이 흔한 업종은 뺀다.
INSTITUTION = re.compile(r"은행|뱅크|카드|캐피탈|금융|증권|저축|공단|법원|검찰|경찰|국세|세무서|관세|연금|정부|시청|구청|군청")
PERSONAL_SENDER = re.compile(r"택배|배송|기사|설계사|보험")
MOBILE = re.compile(r"01[016789]\d{7,8}")

TEMPLATES = {
    RULE_LIST: "문자가 내세운 이름으로 등록해 둔 번호와 입력하신 보낸 번호가 달라요. 등록한 번호 목록이 최신이 아닐 수 있어 사칭이라고 확정한 것은 아니에요.",
    RULE_TYPE: "기관 이름을 내세우는 문자인데 입력하신 보낸 번호가 개인 휴대전화나 해외 번호 형태예요. 그 기관이 실제로 쓰는 번호인지 확인이 필요하고, 사칭이라고 확정한 것은 아니에요.",
}
ACTION = "이 번호로 답하거나 전화하지 말고, 직접 확인한 공식 연락처로 그 기관에 확인하세요."
SPOOF_LIMITATION = "보낸 번호는 바꿔서 표시할 수 있어요. 번호가 맞아 보여도 안전하다는 뜻이 아니며, 번호 확인으로 판정을 낮추지 않아요."
NO_CLAIM_LIMITATION = "문자에서 기관 이름을 찾지 못해 보낸 번호는 비교하지 않았어요."
TYPE_ONLY_LIMITATION = "이 이름으로 등록해 둔 공식 번호가 없어 보낸 번호의 형태만 확인했어요."

SenderType = Literal["mobile", "international", "other"]
ListState = Literal["off", "loaded", "file_missing", "invalid"]


def normalize_number(raw: str) -> str:
    """숫자만 남긴다. +82는 국내 번호(0…)로 바꾸고, 그 밖의 국제 번호는 맨 앞 +를 남긴다."""
    digits = re.sub(r"\D", "", raw)
    if raw.strip().startswith("+"):
        return "0" + digits[2:].lstrip("0") if digits.startswith("82") else "+" + digits
    return digits


def sender_type(number: str) -> SenderType:
    if number.startswith("+") or number.startswith("00"):
        return "international"
    return "mobile" if MOBILE.fullmatch(number) else "other"


@dataclass(frozen=True)
class OfficialNumbers:
    """이름(별칭 포함)별 공식 번호. 번호는 normalize_number 형태다."""

    entries: tuple[tuple[tuple[str, ...], frozenset[str]], ...]

    def numbers_for(self, claimed: str) -> frozenset[str] | None:
        compact = re.sub(r"\s", "", claimed)
        found = [numbers for names, numbers in self.entries if any(name in compact for name in names)]
        return frozenset().union(*found) if found else None


def parse_official_numbers(raw: object) -> OfficialNumbers:
    if not isinstance(raw, dict) or not isinstance(raw.get("organizations"), list):
        raise ValueError
    entries = []
    for item in raw["organizations"]:
        names, numbers = item.get("names"), item.get("numbers")
        if (not isinstance(names, list) or not isinstance(numbers, list) or not names or not numbers
                or not all(isinstance(value, str) for value in [*names, *numbers])):
            raise ValueError
        names = tuple(re.sub(r"\s", "", name) for name in names)
        # 한 글자 이름은 다른 단어 안에서 우연히 맞기 쉽다.
        if any(len(name) < 2 for name in names):
            raise ValueError
        normalized = frozenset(normalize_number(number) for number in numbers)
        if any(len(number.lstrip("+")) < 3 for number in normalized):
            raise ValueError
        entries.append((names, normalized))
    return OfficialNumbers(tuple(entries))


def load_official_numbers(env: dict[str, str]) -> tuple[OfficialNumbers | None, ListState]:
    """목록이 없거나 잘못됐으면 번호 형태 비교만 한다. 서버는 그대로 뜬다."""
    path = env.get(PATH_ENV, "").strip()
    if not path:
        return None, "off"
    file = Path(path)
    try:
        if not file.is_file() or file.stat().st_size > MAX_LIST_BYTES:
            return None, "file_missing" if not file.is_file() else "invalid"
        return parse_official_numbers(json.loads(file.read_text(encoding="utf-8"))), "loaded"
    except (OSError, ValueError, AttributeError):
        return None, "invalid"


@dataclass(frozen=True)
class SenderCheck:
    stage: Literal["completed", "not_applicable"]
    evidence: tuple[Evidence, ...] = ()
    limitations: tuple[str, ...] = ()


def check_sender(sender_number: str | None, findings: list[Finding], official: OfficialNumbers | None = None) -> SenderCheck:
    if not sender_number:
        return SenderCheck("not_applicable")
    number = normalize_number(sender_number)
    kind = sender_type(number)
    # 기관 명의 표현만 본다. 가족 호칭("엄마 나야")과 관계 자기소개("딸인데")는 번호와 비교할 이름이 아니다.
    claims = [f.evidence for f in findings
              if f.evidence.factor_code == FactorCode.IMPERSONATION and f.kind in {"", "header"}
              and not re.search(r"아들|딸|친구", f.evidence.snippet)]
    if not claims:
        return SenderCheck("not_applicable", limitations=(SPOOF_LIMITATION, NO_CLAIM_LIMITATION))
    evidence, type_only = [], False
    for claim in claims:
        listed = official.numbers_for(claim.snippet) if official else None
        if listed is not None:
            rule = RULE_LIST if number not in listed else None
        else:
            type_only = True
            rule = (RULE_TYPE if kind != "other" and INSTITUTION.search(claim.snippet)
                    and not PERSONAL_SENDER.search(claim.snippet) else None)
        if rule:
            evidence.append(Evidence(factor_code=FactorCode.SENDER_MISMATCH, label=LABEL, rule_id=rule,
                                     snippet=claim.snippet, start=claim.start, end=claim.end))
    limitations = (SPOOF_LIMITATION, TYPE_ONLY_LIMITATION) if type_only else (SPOOF_LIMITATION,)
    return SenderCheck("completed", tuple(evidence), limitations)


def combine_sender(level: RiskLevel, reason: str, explanation: str, actions: list[str],
                   evidence: list[Evidence], check: SenderCheck):
    """불일치만 반영한다: 정보 부족 → 의심. 의심·위험은 유지하고, 어떤 경우에도 판정을 낮추지 않는다."""
    if not check.evidence:
        return level, reason, explanation, actions, evidence
    sentences = " ".join(dict.fromkeys(TEMPLATES[item.rule_id] for item in check.evidence))
    if level == RiskLevel.INSUFFICIENT_INFORMATION:
        rest = explanation.removeprefix(HEADINGS[RiskLevel.INSUFFICIENT_INFORMATION]).strip()
        level, reason, explanation = RiskLevel.SUSPICIOUS, REASON, " ".join(filter(None, [sentences, rest]))
    else:
        explanation = f"{explanation} {sentences}"
    return level, reason, explanation, list(dict.fromkeys([ACTION, *actions])), [*evidence, *check.evidence]
