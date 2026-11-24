"""숫자 점수 없이 명시한 개발용 경고 조합. docs/RULE_POLICY.md와 함께 검수한다.

규칙 A·B와 약한 명의 신호(대괄호 머리말, 가족 호칭)는 rules-dev-v3의 임시 정책이며 팀 확정이 필요하다.
"""

import re

from .contracts import FactorCode as F, RiskLevel
from .rule_detection import ACTION_CODES, WEAK_IDENTITY, Finding, RuleScan

# rules-dev-v7(임시): 민감정보를 상대에게 넘기라는 요구(회신·전달·알려 주기 등). 화면에 직접 입력하라는 안내("입력해 주세요")는 넣지 않는다.
CREDENTIAL_HANDOVER = re.compile(r"알려|보내|넘겨|건네|회신|전달|전송|제공|공유")


def decide(scan: RuleScan) -> tuple[RiskLevel, str]:
    contexts: dict[int, list[Finding]] = {}
    for finding in scan.findings:
        contexts.setdefault(finding.context, []).append(finding)
    for found in contexts.values():
        codes = {f.evidence.factor_code for f in found}
        kinds = {(f.evidence.factor_code, f.kind) for f in found}
        # 약한 명의 신호는 기존 조합 1의 명의로 치지 않는다.
        strong_identity = any(code == F.IMPERSONATION and kind not in WEAK_IDENTITY for code, kind in kinds)
        if strong_identity and codes & {F.MONEY_REQUEST, F.CREDENTIAL_REQUEST, F.APP_INSTALL}:
            return RiskLevel.DANGEROUS, "COMBINED_IDENTITY_REQUEST"
        if F.MONEY_REQUEST in codes and codes & {F.CREDENTIAL_REQUEST, F.APP_INSTALL}:
            return RiskLevel.DANGEROUS, "COMBINED_MONEY_REQUEST"
        if {F.URGENCY_THREAT, F.CREDENTIAL_REQUEST, F.LINK_CLICK} <= codes:
            return RiskLevel.DANGEROUS, "COMBINED_URGENT_CREDENTIAL_LINK"
        # v7(임시): 명의(대괄호 머리말·가족 호칭 포함) + 정지·미납 같은 불이익 예고 + 민감정보를 넘기라는 요구.
        # 약한 명의는 조합 1에 넣지 않지만, 불이익 압박과 넘기라는 요구가 함께 있으면 결합 근거로 본다. 입력 안내형은 의심에 둔다.
        if (F.IMPERSONATION in codes and (F.URGENCY_THREAT, "penalty") in kinds
                and any(f.evidence.factor_code == F.CREDENTIAL_REQUEST and CREDENTIAL_HANDOVER.search(f.evidence.snippet) for f in found)):
            return RiskLevel.DANGEROUS, "COMBINED_IDENTITY_PENALTY_HANDOVER"
        # 규칙 A(임시): 명의(머리말 포함) + 불이익 + 링크 요구 + 임박 기한.
        if ({F.IMPERSONATION, F.LINK_CLICK} <= codes
                and {(F.URGENCY_THREAT, "penalty"), (F.URGENCY_THREAT, "deadline")} <= kinds):
            return RiskLevel.DANGEROUS, "COMBINED_NOTICE_PENALTY_DEADLINE"
        # 규칙 B(임시): 가족 호칭 + 금전 요구 + 링크 요구. 답장 유도는 아직 신호가 없다.
        if (F.IMPERSONATION, "family") in kinds and {F.MONEY_REQUEST, F.LINK_CLICK} <= codes:
            return RiskLevel.DANGEROUS, "COMBINED_FAMILY_MONEY_LINK"
        # v6(임시): 혜택·당첨 또는 비밀 유지 요구가 금전·민감정보 요구와 같은 문맥에 있으면 위험.
        if F.BENEFIT_LURE in codes and codes & {F.MONEY_REQUEST, F.CREDENTIAL_REQUEST}:
            return RiskLevel.DANGEROUS, "COMBINED_BENEFIT_REQUEST"
        if F.SECRECY_REQUEST in codes and codes & {F.MONEY_REQUEST, F.CREDENTIAL_REQUEST}:
            return RiskLevel.DANGEROUS, "COMBINED_SECRECY_REQUEST"
    if any({f.evidence.factor_code for f in found} & ACTION_CODES for found in contexts.values()):
        return RiskLevel.SUSPICIOUS, "ACTIONABLE_SIGNAL"
    # v6(임시): 결제·승인 통지나 "본인 아닐 시"와 함께 문자 속 번호로 전화하도록 유도. 단독 문의 번호 안내는 올리지 않는다.
    if any(f.kind == "payment_callback" for f in scan.findings):
        return RiskLevel.SUSPICIOUS, "UNEXPECTED_PAYMENT_CALLBACK"
    # v6(임시): 혜택·당첨 + 기한·소멸 압박 + 주소. 혜택 안내 단독이나 주소 없는 안내는 올리지 않는다.
    if scan.has_url and any(f.kind == "benefit_pressure" for f in scan.findings):
        return RiskLevel.SUSPICIOUS, "BENEFIT_PRESSURE_LINK"
    # 3차(임시): 가족 호칭 + 휴대폰 사정 + 답장·메신저 추가 요청. 금전·링크 요구가 없어도 의심으로 본다(위험으로 올리지 않는다).
    if any(f.kind == "contact" for f in scan.findings):
        return RiskLevel.SUSPICIOUS, "FAMILY_DEVICE_CONTACT"
    return RiskLevel.INSUFFICIENT_INFORMATION, "ANALYSIS_INCOMPLETE"
