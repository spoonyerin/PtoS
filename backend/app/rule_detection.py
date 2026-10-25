"""원문 좌표를 보존하는 제한된 표현 검사. URL 접속·모델 호출은 하지 않는다."""

import re
from bisect import bisect_right
from dataclasses import dataclass, replace

from .contracts import Evidence, FactorCode, InputAssessment
from .urls import extract_urls
from .rule_context import message_contexts

QUOTES = re.compile(r'"[^\"]*"|“[^”]*”|‘[^’]*’|「[^」]*」|\x27[^\x27]*\x27')
BOUNDARY = re.compile(r"[.!?。！？;\n]+|하지만|그러나|그런데|대신|말고")
NEGATION = re.compile(r"지\s*(?:마|말|않)|필요\s*(?:가\s*)?없|아니|아닙|아닌|아닐|안\s*해|금지|거절")
GAP_BREAK = re.compile(r"그리고|하지만|그러나|대신|말고|지\s*(?:마|말|않)|아니|아닙|아닌|아닐|금지|거절")
META = re.compile(r"예시|사례|피싱|사기|예방\s*교육|거절|주의")
REPORT = re.compile(r"라는|라고|라며|같은|처럼|식의")

END = r"(?:주세요|주십시오|주시기\s*바랍니다|줘요?|주셔야\s*(?:합니다|해요))"
BOUND = r"(?=$|[\s.!?。！？,;:\"'”’]|라는|라고|라며|같은|처럼)"
DO = rf"(?:해\s*{END}|하세요|하십시오|하시기\s*바랍니다|해야\s*(?:합니다|해요)|해라){BOUND}"
GIVE = rf"(?:알려|보내|넘겨|건네)\s*{END}{BOUND}"
SEND = rf"보내\s*{END}{BOUND}"

TARGETS = {
    FactorCode.CREDENTIAL_REQUEST: r"인증\s*번호|OTP|비밀\s*번호|주민\s*등록\s*번호|계좌\s*번호|개인\s*정보|카드\s*번호|보안\s*카드",
    FactorCode.MONEY_REQUEST: r"돈|금액|수수료|보증금|현금|대금|송금|입금|이체|결제|\d[\d,]*\s*(?:만\s*)?원",
    FactorCode.LINK_CLICK: r"링크|URL|인터넷\s*주소|아래\s*주소",
    FactorCode.APP_INSTALL: r"앱|어플(?:리케이션)?|애플리케이션|프로그램|APK|원격\s*(?:지원|제어)",
}
ACTIONS = {
    FactorCode.CREDENTIAL_REQUEST: re.compile(rf"{GIVE}|(?:입력|제공|공유|전달|회신|전송){DO}", re.IGNORECASE),
    FactorCode.MONEY_REQUEST: re.compile(rf"{SEND}|(?:송금|입금|이체|결제|납부){DO}|내세요{BOUND}", re.IGNORECASE),
    FactorCode.LINK_CLICK: re.compile(rf"(?:클릭|접속|방문){DO}|(?:눌러|열어)\s*{END}{BOUND}|누르세요{BOUND}", re.IGNORECASE),
    FactorCode.APP_INSTALL: re.compile(rf"(?:설치|다운로드|실행|허용){DO}|(?:설치|다운로드)받아\s*{END}{BOUND}", re.IGNORECASE),
}
TARGET_PATTERN = re.compile("|".join(rf"(?P<{code.value}>{pattern})" for code, pattern in TARGETS.items()), re.IGNORECASE)
IDENTITY = re.compile(
    r"(?:은행|카드사|경찰(?:청|서)?|검찰(?:청)?|금융감독원|국세청|우체국|공공기관|택배사|택배\s*기사)"
    r"\s*(?:의\s*)?(?:(?:고객\s*센터|담당자|직원|상담원|수사관|검사)\s*)?(?:입니다|인데요|이에요|예요)"
    r"|(?:엄마|아빠)[,\s]*(?:나|저)\s*(?:아들|딸)(?:이야|인데|입니다)"
    r"|(?:아들|딸|친구)\s*(?:이야|인데|입니다)"
)
URGENCY = re.compile(r"지금\s*바로|당장|즉시|긴급(?:히|합니다|한)|오늘\s*(?:안에|내로)|\d+\s*분\s*(?:안에|이내)|(?:계좌|서비스|거래)[^.!?\n]*(?:정지|중단)")

LABELS = {
    FactorCode.IMPERSONATION: "기관·지인 명의 주장",
    FactorCode.MONEY_REQUEST: "금전 지급 요구",
    FactorCode.CREDENTIAL_REQUEST: "인증번호·개인정보 요구",
    FactorCode.LINK_CLICK: "링크 클릭·접속 요구",
    FactorCode.APP_INSTALL: "앱 설치·실행 요구",
    FactorCode.URGENCY_THREAT: "긴급성·불이익 압박 표현",
}
ACTION_CODES = frozenset(ACTIONS)


@dataclass(frozen=True)
class Finding:
    evidence: Evidence
    context: int


@dataclass(frozen=True)
class RuleScan:
    findings: list[Finding]
    has_url: bool
    assessment: InputAssessment


def educational_quotes(text: str) -> list[tuple[int, int]]:
    """교육·주의 대상으로 명시한 인용만 제외한다. 문서 전체를 제외하지 않는다."""
    spans = []
    for match in QUOTES.finditer(text):
        prefix = re.split(r"[.!?\n]", text[:match.start()])[-1]
        suffix = re.split(r"[.!?\n]", text[match.end():])[0]
        if META.search(suffix) or (REPORT.search(suffix) and NEGATION.search(suffix)) or re.search(r"(?:예시|사례)\s*[:：]?\s*$", prefix):
            spans.append(match.span())
    return spans


def scan_rules(text: str, *, url_spans: list[tuple[int, int]] | None = None) -> RuleScan:
    urls = extract_urls(text).spans if url_spans is None else url_spans
    # 경로·쿼리의 부정/교육 표현도 문장 해석에 섞이지 않도록 좌표를 유지해 가린다.
    prose = list(text)
    for left, right in urls:
        prose[left:right] = " " * (right - left)
    prose = "".join(prose)
    ignored = educational_quotes(prose)
    findings: list[Finding] = []

    def overlaps(start: int, end: int, spans: list[tuple[int, int]]) -> bool:
        return any(start < right and end > left for left, right in spans)

    def add(code: FactorCode, start: int, end: int):
        if overlaps(start, end, ignored) or (code in {FactorCode.IMPERSONATION, FactorCode.URGENCY_THREAT} and overlaps(start, end, urls)):
            return
        evidence = Evidence(
            factor_code=code, label=LABELS[code], rule_id=f"{code.value.lower()}-v1",
            snippet=text[start:end], start=start, end=end,
        )
        findings.append(Finding(evidence, 0))

    # URL의 마침표와 교육 인용 안의 문장부호는 구절 경계로 사용하지 않는다.
    boundaries = [match for match in BOUNDARY.finditer(prose) if not overlaps(*match.span(), ignored)]
    cursor = 0
    clauses = []
    for boundary in boundaries:
        clauses.append((cursor, boundary.start()))
        cursor = boundary.end()
    clauses.append((cursor, len(text)))

    for start, end in clauses:
        clause = prose[start:end]
        targets = [(m.start(), m.end(), m.lastgroup) for m in TARGET_PATTERN.finditer(clause) if not overlaps(start + m.start(), start + m.end(), urls)]
        targets.extend((left - start, right - start, FactorCode.LINK_CLICK.value) for left, right in urls if start <= left and right <= end)
        targets.sort()
        positions = [target[0] for target in targets]
        for code, pattern in ACTIONS.items():
            for action in pattern.finditer(clause):
                if overlaps(start + action.start(), start + action.end(), urls):
                    continue
                index = bisect_right(positions, action.start()) - 1
                if index < 0:
                    continue
                target = targets[index]
                if target[2] != code.value:
                    continue
                if target[1] > action.start() and target[0] != action.start():
                    continue
                gap = clause[target[1]:action.start()]
                after = clause[action.end():]
                if GAP_BREAK.search(gap):
                    continue
                if REPORT.search(after) and META.search(after):
                    continue
                if re.match(r"\s*(?:라고\s*)?(?:하면|해서는|하시면)\s*안", after):
                    continue
                left, right = start + target[0], start + action.end()
                if not overlaps(left, right, ignored):
                    add(code, left, right)
        for match in IDENTITY.finditer(clause):
            if not NEGATION.search(clause[match.end():]) and not (REPORT.search(clause[match.end():]) and META.search(clause[match.end():])):
                add(FactorCode.IMPERSONATION, start + match.start(), start + match.end())
        for match in URGENCY.finditer(clause):
            if not NEGATION.search(clause[match.end():]):
                if not (REPORT.search(clause[match.end():]) and META.search(clause[match.end():])):
                    add(FactorCode.URGENCY_THREAT, start + match.start(), start + match.end())

    findings.sort(key=lambda finding: (finding.evidence.start, finding.evidence.end, finding.evidence.factor_code))
    contexts, bridged = message_contexts(prose,
        [(f.evidence.factor_code, f.evidence.start, f.evidence.end) for f in findings],
        identity=IDENTITY, urgency=URGENCY, meta=META, quotes=QUOTES)
    findings = [replace(finding, context=context) for finding, context in zip(findings, contexts)]
    if any(f.evidence.factor_code in ACTION_CODES for f in findings):
        assessment = InputAssessment(status="action_identified", reasons=["대상과 긍정적 요구 표현을 규칙으로 확인했어요. 전체 문맥과 실제 신원은 확인하지 못했어요."])
    elif re.search(r"(?:요|니다|다|세요|시오|이야|줘)\s*[.!?。！？\"'”’]*\s*$", prose):
        assessment = InputAssessment(status="sentence_present", reasons=["문장 형태의 입력은 있지만 현재 규칙으로 위험 요구를 확인하지 못했어요. 문맥 분석 모델은 아직 없어요."])
    else:
        assessment = InputAssessment(status="fragment", reasons=["누가 무엇을 요구하는지 확인하기 어려워요. 보낸 사람과 앞뒤 내용을 포함해 입력해주세요."])
    if ignored:
        assessment.reasons.append("교육·주의 대상으로 명시된 인용 구절은 실제 요구로 채택하지 않았어요.")
    if bridged:
        assessment.reasons.append("명의 주장만 있는 도입 문단과 바로 다음의 직접 요구를 제한된 연속 문맥 규칙으로 연결했어요. 표시 없는 화자 전환까지 확인한 것은 아니에요.")
    return RuleScan(findings=findings, has_url=bool(urls), assessment=assessment)
