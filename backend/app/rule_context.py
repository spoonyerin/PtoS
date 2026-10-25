"""원문을 합치지 않고 근거를 결합할 수 있는 제한된 문맥 범위를 정한다."""

import re
from bisect import bisect_right

from .contracts import FactorCode as F

BLANK_LINE = re.compile(r"\r?\n[ \t]*(?:\r?\n[ \t]*)+")
# 명시된 화자/발신자 라벨, 메신저 대괄호 헤더, 인용/메시지 구분선을 경계로 둔다.
MESSAGE_MARKER = re.compile(r"(?m)^[ \t]*(?:[^\s:：\[\]\r\n]+(?:[ \t]+[^\s:：\[\]\r\n]+)*[ \t]*[:：]|\[[^\]\r\n]+\]|>|[-=]{2,})|(?<!\S)(?:[A-Za-z가-힣][\w-]*[ \t]*[:：]|\[[^\]\r\n]+\]|>|[-=]{2,})")
QUOTE_CHARS = frozenset('"\'“”‘’「」')
INTRO_ACTIONS = {F.CREDENTIAL_REQUEST, F.MONEY_REQUEST, F.APP_INSTALL}


def message_contexts(prose: str, signals: list[tuple[F, int, int]], *, identity, urgency, meta, quotes):
    """빈 줄은 기본 경계. 순수 명의 도입→인접 직접 요구만 예외적으로 연결한다."""
    blanks = list(BLANK_LINE.finditer(prose))
    markers = list(MESSAGE_MARKER.finditer(prose))
    quoted = list(quotes.finditer(prose))
    boundaries = sorted({0, *(m.end() for m in blanks), *(m.start() for m in markers),
                         *(edge for m in quoted for edge in m.span())})
    contexts = [bisect_right(boundaries, start) - 1 for _, start, _ in signals]
    parent = list(range(len(boundaries)))
    def root(index):
        while parent[index] != index:
            index = parent[index]
        return index

    starts = [0, *(m.end() for m in blanks)]
    ends = [*(m.start() for m in blanks), len(prose)]
    bridged = False
    for i in range(len(starts) - 1):
        left, right = prose[starts[i]:ends[i]], prose[starts[i + 1]:ends[i + 1]]
        if any(c in QUOTE_CHARS for c in left + right) or meta.search(left + right):
            continue
        if MESSAGE_MARKER.search(left) or MESSAGE_MARKER.search(right):
            continue
        if not identity.fullmatch(left.strip().rstrip(".!?。！？").rstrip()):
            continue
        intro = [n for n, (code, start, _) in enumerate(signals) if code == F.IMPERSONATION and starts[i] <= start < ends[i]]
        following = [n for n, (code, start, _) in enumerate(signals) if code in INTRO_ACTIONS and starts[i + 1] <= start < ends[i + 1]]
        if not intro or not following:
            continue
        if any(code == F.IMPERSONATION and starts[i + 1] <= start < ends[i + 1] for code, start, _ in signals):
            continue
        prefix = prose[starts[i + 1]:signals[following[0]][1]]
        if urgency.sub("", prefix).strip(" \t\r\n.!?。！？"):
            continue
        parent[root(contexts[following[0]])] = root(contexts[intro[0]])
        bridged = True
    return [root(context) for context in contexts], bridged
