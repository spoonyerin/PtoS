"""Explicit development policy; no numeric scores or invented PRD thresholds."""

from .contracts import Evidence, FactorCode, RiskLevel, UrlFinding


def verified_reputation_evidence(urls: list[UrlFinding]) -> list[Evidence]:
    evidence = []
    for url in urls:
        reputation = url.reputation
        if (url.validation_status != "valid" or reputation.status != "malicious"
                or not reputation.full_hash_verified or not reputation.threat_types):
            continue
        for occurrence in url.occurrences:
            evidence.append(Evidence(
                factor_code=FactorCode.URL_REPUTATION_MATCH, label="URL 위협 목록의 전체 해시 일치",
                source="url_reputation", rule_id="verified-url-full-hash-v1",
                snippet=occurrence.text, start=occurrence.start, end=occurrence.end,
            ))
    return evidence


def combine_reputation(level: RiskLevel, reason: str, explanation: str, actions: list[str],
                       evidence: list[Evidence], urls: list[UrlFinding]):
    matches = verified_reputation_evidence(urls)
    if not matches:
        return level, reason, explanation, actions, evidence
    # Report the URL finding, even in an educational quote, without claiming the
    # message's sender is a criminal or inventing an unobserved demand.
    url_explanation = "입력 URL에서 생성한 표현의 전체 해시가 평판 자료의 위협 목록과 일치해 위험할 수 있어요. 문자의 발신자나 사기 여부를 확정한 것은 아니에요."
    if evidence:
        url_explanation = explanation + " " + url_explanation
    return (
        RiskLevel.DANGEROUS, "VERIFIED_URL_THREAT_WITH_RULES" if evidence else "VERIFIED_URL_THREAT",
        url_explanation,
        list(dict.fromkeys(["해당 URL을 열거나 그곳에 정보·인증번호를 입력하지 마세요.",
                            "필요한 업무는 직접 알고 있던 공식 앱이나 연락처에서 별도로 확인하세요.", *actions])),
        [*evidence, *matches],
    )
