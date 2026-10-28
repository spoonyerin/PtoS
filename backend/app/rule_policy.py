"""숫자 점수 없이 명시한 개발용 경고 조합. docs/RULE_POLICY.md와 함께 검수한다.

규칙 A·B와 약한 명의 신호(대괄호 머리말, 가족 호칭)는 rules-dev-v3의 임시 정책이며 팀 확정이 필요하다.
"""

from .contracts import FactorCode as F, RiskLevel
from .rule_detection import ACTION_CODES, WEAK_IDENTITY, Finding, RuleScan


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
        # 규칙 A(임시): 명의(머리말 포함) + 불이익 + 링크 요구 + 임박 기한.
        if ({F.IMPERSONATION, F.LINK_CLICK} <= codes
                and {(F.URGENCY_THREAT, "penalty"), (F.URGENCY_THREAT, "deadline")} <= kinds):
            return RiskLevel.DANGEROUS, "COMBINED_NOTICE_PENALTY_DEADLINE"
        # 규칙 B(임시): 가족 호칭 + 금전 요구 + 링크 요구. 답장 유도는 아직 신호가 없다.
        if (F.IMPERSONATION, "family") in kinds and {F.MONEY_REQUEST, F.LINK_CLICK} <= codes:
            return RiskLevel.DANGEROUS, "COMBINED_FAMILY_MONEY_LINK"
    if any({f.evidence.factor_code for f in found} & ACTION_CODES for found in contexts.values()):
        return RiskLevel.SUSPICIOUS, "ACTIONABLE_SIGNAL"
    return RiskLevel.INSUFFICIENT_INFORMATION, "ANALYSIS_INCOMPLETE"
