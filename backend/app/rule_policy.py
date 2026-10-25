"""숫자 점수 없이 명시한 개발용 경고 조합. docs/RULE_POLICY.md와 함께 검수한다."""

from .contracts import FactorCode as F, RiskLevel
from .rule_detection import ACTION_CODES, RuleScan


def decide(scan: RuleScan) -> tuple[RiskLevel, str]:
    contexts: dict[int, set[F]] = {}
    for finding in scan.findings:
        contexts.setdefault(finding.context, set()).add(finding.evidence.factor_code)
    for codes in contexts.values():
        if F.IMPERSONATION in codes and codes & {F.MONEY_REQUEST, F.CREDENTIAL_REQUEST, F.APP_INSTALL}:
            return RiskLevel.DANGEROUS, "COMBINED_IDENTITY_REQUEST"
        if F.MONEY_REQUEST in codes and codes & {F.CREDENTIAL_REQUEST, F.APP_INSTALL}:
            return RiskLevel.DANGEROUS, "COMBINED_MONEY_REQUEST"
        if {F.URGENCY_THREAT, F.CREDENTIAL_REQUEST, F.LINK_CLICK} <= codes:
            return RiskLevel.DANGEROUS, "COMBINED_URGENT_CREDENTIAL_LINK"
    if any(codes & ACTION_CODES for codes in contexts.values()):
        return RiskLevel.SUSPICIOUS, "ACTIONABLE_SIGNAL"
    return RiskLevel.INSUFFICIENT_INFORMATION, "ANALYSIS_INCOMPLETE"
