"""순수 문자열 URL 처리. 네트워크·DNS·파일 I/O를 사용하지 않는다."""

import ipaddress
import re
import unicodedata
from dataclasses import dataclass, field
from urllib.parse import quote, urlsplit, urlunsplit

import idna

MAX_UNIQUE_URLS = 10
PUBLIC_ERRORS = {
    "INVALID_URL": "http:// 또는 https://로 시작하는 URL 한 개를 입력해주세요. 공백·호스트·포트 등 주소 형식을 확인해주세요.",
    "TOO_MANY_URLS": "URL 후보는 중복을 제외하고 10개 이하로 입력해주세요. 내용을 줄인 뒤 다시 시도해주세요.",
}
START = re.compile(r"(?<![A-Za-z0-9+.-])(?:[A-Za-z][A-Za-z0-9+.-]*://|www\.)", re.IGNORECASE)
DELIMITERS = frozenset('\"\'<>`“”‘’「」『』〈〉《》【】')
TRAILING = frozenset(".,;:!?…。．｡！，、？；：")
PAIRS = {")": "(", "]": "[", "}": "{", "）": "（", "］": "［", "｝": "｛"}


class UrlInputError(ValueError):
    def __init__(self, code: str):
        self.code = code
        super().__init__(PUBLIC_ERRORS[code])


@dataclass(frozen=True)
class ValidatedUrl:
    normalized_url: str
    ascii_host: str


@dataclass(frozen=True)
class Occurrence:
    text: str
    start: int
    end: int


@dataclass
class UrlRecord:
    original_url: str
    value: ValidatedUrl | None
    error: str | None
    warnings: list[str] = field(default_factory=list)
    occurrences: list[Occurrence] = field(default_factory=list)


@dataclass
class UrlExtraction:
    records: list[UrlRecord]

    @property
    def spans(self) -> list[tuple[int, int]]:
        return sorted((o.start, o.end) for r in self.records for o in r.occurrences)


def validate_url(raw: str) -> tuple[ValidatedUrl | None, str | None]:
    if not re.match(r"https?://", raw, re.IGNORECASE):
        return None, "http:// 또는 https://로 시작하는 주소만 지원해요."
    if any(c.isspace() or unicodedata.category(c).startswith("C") for c in raw) or "\\" in raw:
        return None, "주소에 공백·제어 문자·역슬래시가 있어요."
    if any(c in raw for c in '<>\"`') or re.search(r"%(?![0-9a-fA-F]{2})", raw):
        return None, "주소의 문자 또는 퍼센트 인코딩 형식을 확인해주세요."
    try:
        parts = urlsplit(raw)
        if not parts.netloc or not parts.hostname:
            return None, "호스트 이름이 없는 주소예요."
        if parts.username is not None or parts.password is not None:
            return None, "사용자정보가 포함된 주소는 지원하지 않아요."
        host = parts.hostname
        if not host:
            return None, "호스트 이름을 확인해주세요."
        if parts.netloc.startswith("["):
            closing = parts.netloc.find("]")
            suffix = parts.netloc[closing + 1:]
            if ":" not in host or (suffix and not re.fullmatch(r":[0-9]+", suffix)):
                return None, "IPv6 호스트와 포트 형식을 확인해주세요."
        elif "[" in parts.netloc or "]" in parts.netloc:
            return None, "호스트 괄호 형식을 확인해주세요."
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if ":" in host or re.fullmatch(r"[0-9.]+", host):
                return None, "IP 주소 형식을 확인해주세요."
            host_ascii = idna.encode(host, uts46=True, std3_rules=True, transitional=False).decode("ascii").lower().removesuffix(".")
            if len(host_ascii) > 253:
                return None, "도메인 이름이 너무 길어요."
            authority = host_ascii
        else:
            host_ascii = address.compressed.lower()
            if "%" in host_ascii:
                return None, "영역 식별자가 있는 IP 주소는 지원하지 않아요."
            authority = f"[{host_ascii}]" if address.version == 6 else host_ascii
        port = parts.port
        if parts.netloc.endswith(":") or (port is not None and not 1 <= port <= 65535):
            return None, "포트 번호는 1~65535 범위로 입력해주세요."
        scheme = parts.scheme.lower()
        if port is not None and (scheme, port) not in {("http", 80), ("https", 443)}:
            authority += f":{port}"
        def encode(value: str, safe: str) -> str:
            return re.sub(r"%[0-9a-fA-F]{2}", lambda m: m[0].upper(), quote(value, safe=safe + "%"))
        path = encode(parts.path or "/", "/:@!$&'()*+,;=-._~")
        query = encode(parts.query, "/?:@!$&'()*+,;=-._~")
        fragment = encode(parts.fragment, "/?:@!$&'()*+,;=-._~")
        normalized = urlunsplit((scheme, authority, path, query, fragment))
        # 빈 query/fragment 구분자도 원문 의미를 추측해 없애지 않는다.
        before_fragment = raw.split("#", 1)[0]
        if "?" in before_fragment and not parts.query:
            normalized = normalized.replace("#", "?#", 1) if "#" in normalized else normalized + "?"
        if "#" in raw and not parts.fragment:
            normalized += "#"
        return ValidatedUrl(normalized, host_ascii), None
    except (ValueError, UnicodeError, idna.IDNAError):
        return None, "도메인·호스트·포트 형식을 확인해주세요."


def candidates(text: str):
    cursor = 0
    while match := START.search(text, cursor):
        start = match.start()
        end = match.end()
        while end < len(text) and not text[end].isspace() and text[end] not in DELIMITERS:
            if text[end] in ",;" and START.match(text, end + 1):
                break
            end += 1
        raw = text[start:end]
        trim_end = len(raw)
        excess = {closing: raw.count(closing) - raw.count(opening) for closing, opening in PAIRS.items()}
        while trim_end:
            last = raw[trim_end - 1]
            if last in TRAILING:
                trim_end -= 1
            elif last in PAIRS and excess[last] > 0:
                excess[last] -= 1
                trim_end -= 1
            else:
                break
        cleaned = raw[:trim_end]
        warnings = []
        if cleaned != raw:
            warnings.append("문장 끝 구두점이나 짝이 없는 닫는 괄호를 제외했어요. 주소의 일부였다면 URL 직접 입력으로 확인해주세요.")
        if cleaned:
            yield cleaned, start, start + len(cleaned), warnings
        cursor = max(end, match.end())


def extract_urls(text: str, *, direct: bool = False) -> UrlExtraction:
    if direct:
        stripped = text.strip()
        start = len(text) - len(text.lstrip())
        source = [(stripped, start, start + len(stripped), [])]
    else:
        source = candidates(text)
    unique: dict[tuple[str, str], UrlRecord] = {}
    for raw, start, end, warnings in source:
        value, error = validate_url(raw)
        if direct and error:
            raise UrlInputError("INVALID_URL")
        if not direct and value and re.search(r"\.[A-Za-z]{2,}(?:은|는|을|를|에서|으로|로)$", urlsplit(raw).hostname or ""):
            warnings.append("주소에 한글 조사가 붙었을 수 있어요. 원래 주소를 URL 직접 입력으로 확인해주세요.")
        key = ("valid", value.normalized_url) if value else ("invalid", raw)
        if key not in unique:
            if len(unique) >= MAX_UNIQUE_URLS:
                raise UrlInputError("TOO_MANY_URLS")
            unique[key] = UrlRecord(raw, value, error)
        record = unique[key]
        record.occurrences.append(Occurrence(raw, start, end))
        record.warnings = list(dict.fromkeys([*record.warnings, *warnings]))
    return UrlExtraction(list(unique.values()))
