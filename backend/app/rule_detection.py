"""원문 좌표를 보존하는 제한된 표현 검사. URL 접속·모델 호출은 하지 않는다."""

import re
from bisect import bisect_right
from dataclasses import dataclass, replace

from .contracts import Evidence, FactorCode, InputAssessment
from .urls import extract_urls
from .rule_context import message_contexts

QUOTES = re.compile(r'"[^\"]*"|“[^”]*”|‘[^’]*’|「[^」]*」|\x27[^\x27]*\x27')
# "대신 좀 해줘"처럼 대리 행동을 뜻하는 부사는 대조 경계가 아니다.
ON_BEHALF = r"대신(?!\s*(?:좀\s*)?(?:해|보내|송금|결제|이체|입금|내))"
BOUNDARY = re.compile(rf"[.!?。！？;\n]+|하지만|그러나|그런데|{ON_BEHALF}|말고")
NEGATION = re.compile(r"지\s*(?:마|말|않)|필요\s*(?:가\s*)?없|아니|아닙|아닌|아닐|안\s*해|금지|거절")
GAP_BREAK = re.compile(rf"그리고|하지만|그러나|{ON_BEHALF}|말고|지\s*(?:마|말|않)|아니|아닙|아닌|아닐|금지|거절")
META = re.compile(r"예시|사례|피싱|사기|예방\s*교육|거절|주의")
REPORT = re.compile(r"라는|라고|라며|같은|처럼|식의")

# 반말·의문형 요청(줄래?, 줄 수 있어?, 주면 안 돼?)도 요구로 본다. "줄게" 같은 약속형은 넣지 않는다.
END = (r"(?:주세요|주십시오|주시기\s*바랍니다|줘요?|주셔야\s*(?:합니다|해요)|줄래요?"
       r"|줄\s*수\s*(?:있어|있니|있나|있을까|있겠어|있어요|있나요|있을까요)|주실\s*수\s*(?:있나요|있을까요|있으세요|있으신가요)"
       r"|주면\s*안\s*(?:돼|될까|되나|돼요|될까요|되나요))")
BOUND = r"(?=$|[\s.!?。！？,;:\"'”’]|라는|라고|라며|같은|처럼)"
DO = rf"(?:해\s*{END}|하세요|하십시오|하시기\s*바랍니다|해야\s*(?:합니다|해요)|해라){BOUND}"
GIVE = rf"(?:알려|보내|넘겨|건네)\s*{END}{BOUND}"
SEND = rf"보내\s*{END}{BOUND}"

# 링크를 피하라는 안내 동사는 일반 처리 동사로 보지 않는다.
AVOID = r"(?:주의|조심|삭제|자제|차단|신고|무시|경계|유의|거절|거부|피|삼가|멀리)"
# 대동사 "좀 해 줘"와 금전 대상 사이에 다른 업무 명사가 끼면 금전 요구로 연결하지 않는다.
PROXY_GAP = re.compile(r"확인|조회|문의|신청|변경|취소|안내|내역")

TARGETS = {
    FactorCode.CREDENTIAL_REQUEST: r"인증\s*번호|OTP|비밀\s*번호|주민\s*등록\s*번호|계좌\s*번호|개인\s*정보|카드\s*번호|보안\s*카드",
    FactorCode.MONEY_REQUEST: r"돈|금액|수수료|보증금|현금|대금|송금|입금|이체|결제|상품권|기프트\s*카드|\d[\d,]*\s*(?:만\s*)?원",
    FactorCode.LINK_CLICK: r"링크|URL|인터넷\s*주소|아래\s*주소",
    FactorCode.APP_INSTALL: r"앱|어플(?:리케이션)?|애플리케이션|프로그램|APK|원격\s*(?:지원|제어)",
}
ACTIONS = {
    FactorCode.CREDENTIAL_REQUEST: re.compile(rf"{GIVE}|(?:입력|제공|공유|전달|회신|전송){DO}", re.IGNORECASE),
    FactorCode.MONEY_REQUEST: re.compile(rf"{SEND}|(?:빌려|사|부쳐)\s*{END}{BOUND}|(?:송금|입금|이체|결제|납부){DO}|내세요{BOUND}"
                                         rf"|(?:좀\s*)?부탁(?:해요?|할게요?|드려요|드립니다|합니다){BOUND}"
                                         rf"|(?P<proxy>(?<![가-힣])(?:대신\s*)?(?:좀\s*)?해\s*{END}{BOUND})", re.IGNORECASE),
    FactorCode.LINK_CLICK: re.compile(rf"(?:클릭|접속|방문){DO}|(?:눌러|열어)\s*{END}{BOUND}|누르세요{BOUND}"
                                      rf"|(?P<confirm>(?:확인|조회)\s*(?:{DO}|(?:바랍니다|부탁드립니다|부탁드려요|요망){BOUND}|해\s*봐요?{BOUND}))"
                                      rf"|(?P<guided>(?:눌러|클릭해|접속해|들어가)서?[^.!?\n]{{0,30}}?(?:{END}|{DO}|해\s*봐요?|부탁(?:해요?|드려요|드립니다)|줘){BOUND}"
                                      rf"|(?<![가-힣])(?!{AVOID})[가-힣]{{1,8}}?\s*(?:{DO}|(?:바랍니다|요망){BOUND}))", re.IGNORECASE),
    FactorCode.APP_INSTALL: re.compile(rf"(?:설치|다운로드|실행|허용){DO}|(?:설치|다운로드)받아\s*{END}{BOUND}", re.IGNORECASE),
}
# "여기·이곳"은 메시지에 URL이 있을 때만, 명시적 접속 동사(눌러, 접속해 등)와 함께 링크 대상으로 본다.
POINTER = re.compile(r"여기|이곳")
EXPLICIT_LINK = re.compile(r"클릭|접속|방문|눌러|누르|열어|들어가")
TARGET_PATTERN = re.compile("|".join(rf"(?P<{code.value}>{pattern})" for code, pattern in TARGETS.items()), re.IGNORECASE)
IDENTITY = re.compile(
    r"(?:은행|카드사|경찰(?:청|서)?|검찰(?:청)?|금융감독원|국세청|우체국|공공기관|택배사|택배\s*기사)"
    r"\s*(?:의\s*)?(?:(?:고객\s*센터|담당자|직원|상담원|수사관|검사)\s*)?(?:입니다|인데요|이에요|예요)"
    r"|(?:엄마|아빠)[,\s]*(?:나|저)\s*(?:아들|딸)(?:이야|인데|입니다)"
    r"|(?:아들|딸|친구)\s*(?:이야|인데|입니다)"
)
URGENCY_DEADLINE = r"지금\s*바로|당장|즉시|긴급(?:히|합니다|한)|오늘\s*(?:안에|내로)|\d+\s*분\s*(?:안에|이내)"
URGENCY_PENALTY = r"(?:계좌|서비스|거래)[^.!?\n]*(?:정지|중단)"
URGENCY = re.compile(f"{URGENCY_DEADLINE}|{URGENCY_PENALTY}")

# 임시(rules-dev-v3): 대괄호 머리말 안의 기관·업종 단어. 머리말 단독으로는 판정을 올리지 않는다.
HEADER_RUN = re.compile(r"(?m)^[ \t]*(?:\[[^\]\r\n]{1,20}\][ \t]*)+")
BRACKET = re.compile(r"\[[^\]\r\n]{1,20}\]")
HEADER_SECTOR = re.compile(
    r"은행|뱅크|카드|캐피탈|금융|증권|저축|보험|공단|공사|법원|검찰|경찰|우체국|우정|우편|택배|배송|통운|물류|로지스"
    r"|통신|텔레콤|국세|세무|관세|연금|정부|시청|구청|군청|도로|하이패스|민원|센터|보안|통지|통보|고지|위반|채용|계정"
    r"|그룹|주식회사|㈜|\(주\)|[청부처]\]$")
# 임시: 줄 첫머리에서 부모·조부모를 부르고 바로 1인칭으로 말하거나 휴대폰 고장·분실을 설명하는 말투.
FAMILY_CALL = r"(?:엄마|아빠|어머니|아버지|어머님|아버님|할머니|할아버지)"
FAMILY = re.compile(
    rf"(?m)^[ \t]*{FAMILY_CALL}[\s,~!.]*(?:(?:나|저)(?=야|예요|에요|요|[\s,.!?~]|$)"
    r"|[^\n.!?]{0,20}?(?:폰|휴대폰|핸드폰|전화기?)\s*(?:이|가)?\s*(?:고장|액정|깨[져졌]|분실|잃어버|망가|물에))")
# 임시: 청구어는 단독으로, 상태 변화어는 예고·조건 형태일 때만 불이익으로 본다. 과거형 완료 안내는 제외한다.
PENALTY = re.compile(
    r"미납|연체|체납|과태료|범칙금|벌금|가산금|가산세|압류|강제\s*집행|법적\s*(?:조치|절차|처벌)"
    r"|(?:정지|중지|만료|취소|반송|제한|해지|차단|폐기|말소)(?=\s*(?:처리|조치)?\s*(?:예정|될|됩니다|되오니|되며|되니|돼요|됨|할\s*예정))"
    r"|(?:시|경우|면)\s*(?:자동\s*)?(?:으로\s*)?(?:정지|중지|만료|취소|반송|제한|해지|차단|폐기|말소)")
# 임시: 임박 기한(당일·금일·오늘·내일·익일 + 기한 표현, 자정까지, 24시간 이내, 1일 남음). 날짜만 적힌 기한은 해석하지 않는다.
DAY = r"(?:당일|금일|오늘|내일|익일)"
DEADLINE = re.compile(
    rf"{DAY}\s*(?:\(\s*\d{{1,2}}\s*일\s*\)\s*)?(?:중|까지|안에|안으로|내|내로|이내|자정|마감"
    r"|(?:오전|오후|밤|저녁)?\s*\d{1,2}\s*시\s*(?:까지|전|부로|부터|예정|에|\)))"
    r"|자정\s*(?:까지|전)|(?<!\d)(?:[1-9]|1\d|2[0-4])\s*시간\s*(?:이내|내|안에|안|후|뒤)"
    r"|(?<!\d)1\s*일\s*(?:남음|남았|이내|내|안에)|D\s*-\s*(?:day|0|1)(?!\d)", re.IGNORECASE)
# 임시: "확인: 주소", "조회하세요 ▶ 주소"처럼 확인 안내 바로 뒤에 URL이 오는 형태.
CONFIRM_BEFORE_URL = re.compile(
    r"(?:확인|조회|접속|바로\s*가기|상세\s*보기|자세히\s*보기)"
    rf"(?:\s*(?:하기|{DO}|(?:바랍니다|부탁드립니다|부탁드려요|요망)))?[ \t]*[.:：▶►>☞→]*[ \t]*(?:\r?\n[ \t]*)?$")
LABEL_BEFORE_URL = re.compile(r"(?<![^\s.!?。！？,])[가-힣]{1,8}(?:[ \t]+(?:및[ \t]+)?[가-힣]{1,8}){0,3}[ \t]*[:：▶►☞→][ \t]*$")

LABELS = {
    FactorCode.IMPERSONATION: "기관·지인 명의 주장",
    FactorCode.MONEY_REQUEST: "금전 지급 요구",
    FactorCode.CREDENTIAL_REQUEST: "인증번호·개인정보 요구",
    FactorCode.LINK_CLICK: "링크 클릭·접속 요구",
    FactorCode.APP_INSTALL: "앱 설치·실행 요구",
    FactorCode.URGENCY_THREAT: "긴급성·불이익 압박 표현",
}
ACTION_CODES = frozenset(ACTIONS)
WEAK_IDENTITY = frozenset({"header", "family"})


@dataclass(frozen=True)
class Finding:
    evidence: Evidence
    context: int
    # 정책용 세부 유형(header, family, deadline, penalty). 계약에는 rule_id로만 드러난다.
    kind: str = ""


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

    def add(code: FactorCode, start: int, end: int, kind: str = "", rule: str = ""):
        if overlaps(start, end, ignored) or (code in {FactorCode.IMPERSONATION, FactorCode.URGENCY_THREAT} and overlaps(start, end, urls)):
            return
        # 같은 구절을 기존 패턴과 새 패턴이 함께 잡으면 먼저 찾은 근거만 남긴다.
        if any(f.evidence.factor_code == code and start < f.evidence.end and end > f.evidence.start for f in findings):
            return
        evidence = Evidence(
            factor_code=code, label=LABELS[code], rule_id=f"{code.value.lower()}{'-' + rule if rule else ''}-v1",
            snippet=text[start:end], start=start, end=end,
        )
        findings.append(Finding(evidence, 0, kind))

    def asserted(clause: str, end: int) -> bool:
        after = clause[end:]
        return not NEGATION.search(after) and not (REPORT.search(after) and META.search(after))

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
        if urls:
            targets.extend((m.start(), m.end(), "POINTER") for m in POINTER.finditer(clause))
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
                if target[2] == "POINTER" and code == FactorCode.LINK_CLICK and EXPLICIT_LINK.match(action.group()):
                    pass
                elif target[2] != code.value:
                    continue
                if target[1] > action.start() and target[0] != action.start():
                    continue
                gap = clause[target[1]:action.start()]
                after = clause[action.end():]
                if GAP_BREAK.search(gap):
                    continue
                if action.groupdict().get("proxy") and PROXY_GAP.search(gap):
                    continue
                if REPORT.search(after) and META.search(after):
                    continue
                if re.match(r"\s*(?:라고\s*)?(?:하면|해서는|하시면)\s*안", after):
                    continue
                left, right = start + target[0], start + action.end()
                if not overlaps(left, right, ignored):
                    groups = action.groupdict()
                    add(code, left, right, rule="confirm" if groups.get("confirm") else "guided" if groups.get("guided") else "")
        for match in IDENTITY.finditer(clause):
            if asserted(clause, match.end()):
                add(FactorCode.IMPERSONATION, start + match.start(), start + match.end())
        for match in URGENCY.finditer(clause):
            if asserted(clause, match.end()):
                kind = "penalty" if re.fullmatch(URGENCY_PENALTY, match.group()) else "deadline"
                add(FactorCode.URGENCY_THREAT, start + match.start(), start + match.end(), kind)
        for pattern, kind in ((PENALTY, "penalty"), (DEADLINE, "deadline")):
            for match in pattern.finditer(clause):
                if asserted(clause, match.end()):
                    add(FactorCode.URGENCY_THREAT, start + match.start(), start + match.end(), kind, kind)
        # 기한 표현 없는 날짜어("익일 서비스 해지 예정")는 같은 구절에 불이익 예고가 있을 때만 기한으로 본다.
        if PENALTY.search(clause):
            for match in re.finditer(DAY, clause):
                if asserted(clause, match.end()):
                    add(FactorCode.URGENCY_THREAT, start + match.start(), start + match.end(), "deadline", "deadline")

    # 줄 단위 형태(머리말, 가족 호칭, 주소 앞 확인 안내)는 구절로 나누기 전의 원문 좌표에서 찾는다.
    for run in HEADER_RUN.finditer(prose):
        for match in BRACKET.finditer(prose, run.start(), run.end()):
            if HEADER_SECTOR.search(match.group()):
                add(FactorCode.IMPERSONATION, *match.span(), "header", "header")
    for match in FAMILY.finditer(prose):
        left = match.start() + len(match.group()) - len(match.group().lstrip())
        add(FactorCode.IMPERSONATION, left, match.end(), "family", "family")
    for left, right in urls:
        prefix = prose[max(0, left - 40):left]
        match = CONFIRM_BEFORE_URL.search(prefix)
        rule = "confirm"
        if not match:
            match, rule = LABEL_BEFORE_URL.search(prefix), "guided"
        if match and not NEGATION.search(prefix[match.start():]):
            add(FactorCode.LINK_CLICK, left - len(prefix) + match.start(), right, rule=rule)

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
