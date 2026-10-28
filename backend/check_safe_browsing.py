"""Run from backend: python check_safe_browsing.py --live [--timeout 초] [--probe official-example [--variant 이름]]

Google Safe Browsing v5 hashes.search를 사람이 직접 한 번 확인하는 수동 스크립트다. 자동 테스트에 넣지 않는다.
- --live 옵션, GOOGLE_SAFE_BROWSING_API_KEY, PTOS_SAFE_BROWSING_MODE=live-noncommercial이 모두 있을 때만 호출한다.
- 사용자 입력은 받지 않는다. 아래 고정 테스트 URL의 해시 접두사만 1회 조회하고, 그 URL에는 접속하지 않는다.
- --probe official-example은 테스트 URL 대신 공식 개요 예시 접두사(WwuJdQ) 1개만 보낸다. 키 문제와 접두사 형식 문제를 가른다.
- --variant(no-alt, key-query, padded, official-exact)는 probe의 요청 모양만 바꾼다. 앱 전송기는 그대로다.
  key-query·official-exact는 키가 URL 쿼리에 들어가므로 URL·예외 메시지를 출력하지 않고 httpx 로그를 막는다.
- 키·접두사·전체 해시는 출력하지 않는다. 앱과 같은 정규화·해시·응답 대조(SafeBrowsingV5Provider)를 거친다.
- 이 스크립트에서만 HTTP 오류 본문을 최대 16 KiB 읽어 짧은 분류 값(error.status, details[].reason 등)만 출력한다.
  오류 message·description 원문은 출력하지 않는다. 앱의 전송기는 계속 오류 본문을 읽지 않는다.

테스트 URL 출처: Google 공식 GitHub 저장소 google/safebrowsing의 README(sblookup 예시,
https://github.com/google/safebrowsing). v4 참조 구현의 예시이며 v5 문서에서는 테스트 URL 목록을 찾지 못했다.
v5에서 이 URL이 위협 목록과 일치한다는 보장은 없다.
공식 예시 접두사 출처: https://developers.google.com/safe-browsing/reference (hashes.search 예시 요청 hashPrefixes=WwuJdQ)
"""

import argparse
import asyncio
from collections.abc import Mapping
from dataclasses import dataclass
import json
import logging
import os
import re
import sys
import time

import httpx

from app.safe_browsing import SEARCH_ENDPOINT, SafeBrowsingV5Provider, SearchResponse, TransportNetworkError, TransportResponseError, TransportTimeout
from app.safe_browsing_http import MAX_RESPONSE_BYTES, HttpxHashSearchTransport
from app.url_reputation import API_KEY_ENV, DEFAULT_TIMEOUT, LIVE_MODE, MODE_ENV, TIMEOUT_ENV
from app.urls import extract_urls

TEST_URL = "http://testsafebrowsing.appspot.com/apiv4/ANY_PLATFORM/MALWARE/URL/"
TEST_URL_SOURCE = "https://github.com/google/safebrowsing (README, sblookup 예시, v4 참조 구현)"
OFFICIAL_EXAMPLE_PREFIX = "WwuJdQ"
OFFICIAL_EXAMPLE_SOURCE = "https://developers.google.com/safe-browsing/reference (hashes.search 예시 요청)"
MAX_TIMEOUT = 30.0
# 진단용으로 읽는 오류 본문의 최대 크기(개발 제안).
MAX_ERROR_BODY_BYTES = 16 * 1024

UPPER_CODE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")
TYPE_NAME = re.compile(r"[A-Za-z0-9_]{1,64}")
FIELD_NAME = re.compile(r"[A-Za-z0-9_.\[\]]{1,64}")
CONTENT_TYPE = re.compile(r"[A-Za-z0-9!#$&^_.+\-/;= ]{1,100}")
OMITTED = "(형식 밖 값 생략)"
CACHE_DURATION = re.compile(r"[0-9]{1,12}(?:\.[0-9]{1,9})?s")

# 변형 요청은 키가 URL 쿼리에 들어갈 수 있다. httpx는 INFO에서 전체 URL을, httpcore는 DEBUG에서
# 헤더를 기록하므로 이 스크립트에서는 두 로거를 WARNING으로 고정하고 상위 로거로 전파하지 않는다.
for _name in ("httpx", "httpcore"):
    logging.getLogger(_name).setLevel(logging.WARNING)
    logging.getLogger(_name).propagate = False


@dataclass(frozen=True)
class Variant:
    key_in_query: bool
    alt_json: bool
    accept_json: bool
    prefix: str
    description: str


# --probe official-example 전용 요청 변형. 앱 전송기(app/)의 요청 모양은 바꾸지 않는다.
VARIANTS = {
    "no-alt": Variant(False, False, False, OFFICIAL_EXAMPLE_PREFIX,
                      "키: X-Goog-Api-Key 헤더, alt: 없음, Accept: httpx 기본값, 접두사: padding 없음"),
    "key-query": Variant(True, True, True, OFFICIAL_EXAMPLE_PREFIX,
                         "키: 쿼리 매개변수 key, alt=json, Accept: application/json, 접두사: padding 없음"),
    "padded": Variant(False, True, True, OFFICIAL_EXAMPLE_PREFIX + "==",
                      "키: X-Goog-Api-Key 헤더, alt=json, Accept: application/json, 접두사: padding 있음"),
    "official-exact": Variant(True, False, False, OFFICIAL_EXAMPLE_PREFIX,
                              "공식 개요 예시와 같은 형태 (쿼리 매개변수 key와 hashPrefixes만), Accept: httpx 기본값"),
}


def _short(value, pattern: re.Pattern) -> str | None:
    if value is None:
        return None
    return value if isinstance(value, str) and pattern.fullmatch(value) else OMITTED


def summarize_error_body(content_type: str, data: bytes, truncated: bool) -> list[str]:
    """오류 본문에서 짧은 분류 값만 뽑는다. message·description·metadata 원문은 돌려주지 않는다."""
    shown_type = content_type if CONTENT_TYPE.fullmatch(content_type or "") else "(없음 또는 형식 밖)"
    if truncated:
        return [f"오류 본문: {MAX_ERROR_BODY_BYTES // 1024} KiB를 넘어 분석하지 않았어요 (Content-Type: {shown_type})"]
    if (content_type or "").split(";")[0].strip().lower() != "application/json":
        return [f"오류 본문: JSON이 아니에요 (Content-Type: {shown_type})"]
    try:
        body = json.loads(data)
    except ValueError:
        return [f"오류 본문: JSON이 아니에요 (Content-Type: {shown_type})"]
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return ["오류 본문: error 객체가 없어요"]
    lines = []
    code = error.get("code")
    lines.append(f"error.code: {code if isinstance(code, int) and not isinstance(code, bool) else OMITTED}")
    lines.append(f"error.status: {_short(error.get('status'), UPPER_CODE) or '(없음)'}")
    message = error.get("message")
    message = message if isinstance(message, str) else ""
    # message 원문은 출력하지 않고 안에서만 검사해 참/거짓만 낸다.
    lines.append(f"message_mentions_base64: {str(bool(re.search(r'base64|type_bytes', message, re.IGNORECASE))).lower()}")
    lines.append(f"message_mentions_api_key: {str(bool(re.search(r'api[ _-]?key', message, re.IGNORECASE))).lower()}")
    details = error.get("details")
    if isinstance(details, list) and details:
        names = []
        for detail in details[:10]:
            raw_type = detail.get("@type") if isinstance(detail, dict) else None
            names.append(_short(re.split(r"[/.]", raw_type)[-1], TYPE_NAME) if isinstance(raw_type, str) else "(없음)")
        lines.append(f"error.details: {len(details)}개 (@type: {', '.join(names)})")
    else:
        lines.append("error.details: 없음")
    for index, detail in enumerate(details[:10] if isinstance(details, list) else []):
        if not isinstance(detail, dict):
            continue
        raw_type = detail.get("@type")
        type_name = _short(re.split(r"[/.]", raw_type)[-1], TYPE_NAME) if isinstance(raw_type, str) else None
        parts = [f"@type={type_name or '(없음)'}"]
        if "reason" in detail:
            parts.append(f"reason={_short(detail.get('reason'), UPPER_CODE)}")
        violations = detail.get("fieldViolations")
        if isinstance(violations, list):
            fields = [_short(v.get("field"), FIELD_NAME) or "(없음)" for v in violations[:10] if isinstance(v, dict)]
            parts.append(f"fieldViolations.field=[{', '.join(fields)}]")
        lines.append(f"error.details[{index}]: {' '.join(parts)}")
    return lines


class ErrorBodyDiagnostics(httpx.AsyncBaseTransport):
    """수동 확인 전용. 200이 아닌 응답 본문을 제한된 크기만 읽어 분류 값으로 요약하고, 본문은 비워서 넘긴다."""

    def __init__(self, inner: httpx.AsyncBaseTransport):
        self.inner = inner
        self.summary: list[str] | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        response = await self.inner.handle_async_request(request)
        if response.status_code == 200:
            return response
        content_type = response.headers.get("content-type", "")
        data, truncated = bytearray(), False
        try:
            async for chunk in response.aiter_bytes():
                if len(data) + len(chunk) > MAX_ERROR_BODY_BYTES:
                    truncated = True
                    break
                data.extend(chunk)
        finally:
            await response.aclose()
        self.summary = summarize_error_body(content_type, bytes(data), truncated)
        data.clear()
        # 앱 전송기는 오류 본문을 읽지 않으므로 상태 코드만 그대로 넘긴다.
        return httpx.Response(response.status_code, headers=[("content-type", content_type)] if content_type else [])

    async def aclose(self) -> None:
        await self.inner.aclose()


class RecordingTransport:
    """실제 전송기를 감싸 진단 정보(상태 코드, 형식, 지연, cacheDuration)만 기록한다."""

    def __init__(self, inner):
        self.inner = inner
        self.calls = 0
        self.prefix_count = 0
        self.status_code: int | None = None
        self.content_type: str | None = None
        self.cache_duration: str | None = None
        self.full_hash_count: int | None = None
        self.error: str | None = None
        self.elapsed_ms: float | None = None

    async def search(self, hash_prefixes: tuple[str, ...]) -> SearchResponse:
        self.calls += 1
        self.prefix_count = len(hash_prefixes)
        started = time.perf_counter()
        try:
            response = await self.inner.search(hash_prefixes)
        except TransportResponseError as error:
            self.error, self.content_type = "응답 형식 오류", error.content_type or "(없음)"
            raise
        except TransportTimeout:
            self.error = "전송 시간 초과"
            raise
        except TransportNetworkError:
            self.error = "네트워크 오류"
            raise
        finally:
            self.elapsed_ms = (time.perf_counter() - started) * 1000
        self.status_code = response.status_code
        if response.status_code == 200:
            self.content_type = "application/json"
            self.cache_duration = response.body.get("cacheDuration")
            records = response.body.get("fullHashes", [])
            self.full_hash_count = len(records) if isinstance(records, list) else None
        return response

    async def aclose(self) -> None:
        await self.inner.aclose()


def refuse(message: str) -> int:
    print(f"[중단] {message}")
    print("외부 호출을 하지 않았어요.")
    return 2


def print_diagnostics(recorder: RecordingTransport, diagnostics: ErrorBodyDiagnostics, timeout: float) -> None:
    print(f"호출 횟수: {recorder.calls}회 / 보낸 접두사 개수: {recorder.prefix_count}개")
    if recorder.elapsed_ms is not None:
        print(f"응답 시간: {recorder.elapsed_ms:.0f} ms (이번 확인의 제한 {timeout:g}초)")
    print(f"HTTP 상태: {recorder.status_code if recorder.status_code is not None else '(응답 없음)'}")
    print(f"Content-Type: {recorder.content_type or '(확인 안 됨)'}")
    if recorder.cache_duration is not None:
        print(f"cacheDuration: {recorder.cache_duration}")
    if recorder.full_hash_count is not None:
        print(f"응답의 전체 해시 개수: {recorder.full_hash_count}")
    if recorder.error:
        print(f"전송 단계 문제: {recorder.error}")
    for line in diagnostics.summary or []:
        print(line)
    if diagnostics.summary:
        text = "\n".join(diagnostics.summary)
        if "API_KEY" in text or "message_mentions_api_key: true" in text:
            print("[참고] 오류 분류에 API 키 관련 표시가 있어요. 키 값·제한 설정을 확인해주세요.")
        if "message_mentions_base64: true" in text or re.search(r"hash_?prefixes", text, re.IGNORECASE):
            print("[참고] 오류 분류가 해시 접두사(형식)를 가리켜요. 접두사 인코딩 결정에 이 출력을 공유해주세요.")


async def probe_variant(key: str, name: str, timeout: float, transport=None) -> int:
    """공식 예시 접두사 1개로 요청 모양만 바꿔 1회 호출한다.

    키가 URL 쿼리에 들어갈 수 있으므로 요청·응답 URL, Location 헤더, 예외 메시지는 어디에도 출력하지 않는다.
    출력은 고정 항목과 예외 클래스 이름뿐이다.
    """
    variant = VARIANTS[name]
    diagnostics = ErrorBodyDiagnostics(transport if transport is not None else httpx.AsyncHTTPTransport())
    params = [("key", key)] if variant.key_in_query else []
    params.append(("hashPrefixes", variant.prefix))
    if variant.alt_json:
        params.append(("alt", "json"))
    headers = {} if variant.key_in_query else {"X-Goog-Api-Key": key}
    if variant.accept_json:
        headers["Accept"] = "application/json"

    status_code = content_type = cache_duration = error_name = None
    size = full_hash_count = None
    json_body = None
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False, transport=diagnostics) as client:
            async with asyncio.timeout(timeout):
                async with client.stream("GET", SEARCH_ENDPOINT, params=params, headers=headers) as response:
                    status_code = response.status_code
                    content_type = response.headers.get("content-type", "")
                    if status_code == 200:
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > MAX_RESPONSE_BYTES:
                                break
                        size = len(data)
                        if content_type.split(";")[0].strip().lower() == "application/json" and size <= MAX_RESPONSE_BYTES:
                            try:
                                json_body = json.loads(bytes(data))
                            except ValueError:
                                json_body = None
                        data.clear()
    except Exception as error:  # noqa: BLE001 - 메시지에 키가 담긴 URL이 들어갈 수 있어 클래스 이름만 쓴다.
        error_name = type(error).__name__ if TYPE_NAME.fullmatch(type(error).__name__) else "Exception"
    elapsed_ms = (time.perf_counter() - started) * 1000
    if isinstance(json_body, dict):
        value = json_body.get("cacheDuration")
        cache_duration = value if isinstance(value, str) and CACHE_DURATION.fullmatch(value) else OMITTED if value is not None else None
        records = json_body.get("fullHashes", [])
        full_hash_count = len(records) if isinstance(records, list) else None

    print(f"확인 방식: 공식 예시 접두사 1개 + 요청 변형 {name} (출처: {OFFICIAL_EXAMPLE_SOURCE})")
    print(f"요청 형태: {variant.description}")
    print("호출 횟수: 1회 / 보낸 접두사 개수: 1개")
    print(f"응답 시간: {elapsed_ms:.0f} ms (이번 확인의 제한 {timeout:g}초)")
    print(f"HTTP 상태: {status_code if status_code is not None else '(응답 없음)'}")
    if content_type is not None:
        print(f"Content-Type: {content_type if CONTENT_TYPE.fullmatch(content_type) else '(없음 또는 형식 밖)'}")
    if size is not None:
        print(f"본문 크기: {size} 바이트{' (상한 초과로 중단)' if size > MAX_RESPONSE_BYTES else ''}")
    if status_code == 200 and json_body is None:
        print("응답 형식: 200, JSON이 아니에요 (디코딩하지 않았어요)")
    if cache_duration is not None:
        print(f"cacheDuration: {cache_duration}")
    if full_hash_count is not None:
        print(f"응답의 전체 해시 개수: {full_hash_count}")
    if error_name:
        print(f"전송 단계 문제: {error_name}")
    for line in diagnostics.summary or []:
        print(line)
    if status_code == 200:
        print(f"[확인] 변형 {name}으로 200을 받았어요. 이 출력을 공유해주세요. 앱 전송기 수정은 따로 승인받은 뒤 해요.")
        return 0
    print(f"[실패] 변형 {name}으로도 조회하지 못했어요. 위 상태와 오류 분류를 확인해주세요.")
    return 1


async def check(env: Mapping[str, str], timeout: float, transport=None, probe: str | None = None, variant: str | None = None) -> int:
    key = env.get(API_KEY_ENV, "").strip()
    if not key:
        return refuse(f"{API_KEY_ENV}가 없어요. 백엔드 환경 변수로만 넣어주세요.")
    if env.get(MODE_ENV, "") != LIVE_MODE:
        return refuse(f"{MODE_ENV}={LIVE_MODE} 가 정확히 설정되어 있지 않아요.")
    if variant is not None:
        print("Google Safe Browsing v5 hashes.search 수동 확인 (요청 변형 진단)")
        return await probe_variant(key, variant, timeout, transport)
    diagnostics = ErrorBodyDiagnostics(transport if transport is not None else httpx.AsyncHTTPTransport())
    recorder = RecordingTransport(HttpxHashSearchTransport(key, timeout=timeout, transport=diagnostics))

    print("Google Safe Browsing v5 hashes.search 수동 확인 (저장소 없는 실시간 모드)")
    if probe == "official-example":
        print(f"확인 방식: 공식 예시 접두사 1개만 조회 (출처: {OFFICIAL_EXAMPLE_SOURCE})")
        try:
            async with asyncio.timeout(timeout):
                await recorder.search((OFFICIAL_EXAMPLE_PREFIX,))
        except (TimeoutError, TransportTimeout):
            recorder.error = recorder.error or "전송 시간 초과"
        except (TransportNetworkError, TransportResponseError):
            pass
        finally:
            await recorder.aclose()
        print_diagnostics(recorder, diagnostics, timeout)
        if recorder.status_code == 200:
            print("[확인] 공식 예시 접두사로는 200이에요. 키와 기본 요청은 정상이고, 문제는 테스트 URL 접두사 쪽일 가능성이 커요.")
            return 0
        print("[실패] 공식 예시 접두사로도 조회하지 못했어요. 위 오류 분류를 확인해주세요.")
        return 1

    value = extract_urls(TEST_URL, direct=True).records[0].value
    # 이 스크립트 실행에서 호출은 최대 1회다.
    provider = SafeBrowsingV5Provider(recorder, per_minute=1, per_day=1, timeout=timeout)
    try:
        result = await provider.lookup(value)
    finally:
        await provider.aclose()

    print(f"테스트 URL: {TEST_URL}")
    print(f"테스트 URL 출처: {TEST_URL_SOURCE}")
    print("이 URL에는 접속하지 않았고, 4바이트 해시 접두사만 보냈어요.")
    print_diagnostics(recorder, diagnostics, timeout)
    print(f"결과: status={result.status}, reason={result.reason}")
    print(f"위협 유형: {', '.join(result.threat_types) if result.threat_types else '(없음)'}")

    if recorder.elapsed_ms is not None and recorder.elapsed_ms > DEFAULT_TIMEOUT * 1000:
        print(f"[참고] 응답 시간이 앱 기본 제한({DEFAULT_TIMEOUT:g}초)보다 길어요. 앱에서는 {TIMEOUT_ENV}로 조정할 수 있어요.")
    if result.status == "malicious":
        print("[확인] 전체 해시와 위협 유형이 일치했어요. 위협 일치 흐름이 실제 API로 동작해요.")
        return 0
    if (result.status, result.reason) == ("unknown", "no_match"):
        print("[안내] 일치 결과가 없어요. 오류가 아니에요. 이 테스트 URL은 v4 예시라 v5에서 일치하지 않을 수 있어요.")
        print("       결과 없음은 안전 판정이 아니에요.")
        return 0
    if result.status == "unknown":
        print("[안내] 일치한 해시가 있지만 현재 경고에 쓰지 않는 위협 유형·속성이에요.")
        return 0
    if recorder.content_type and recorder.content_type != "application/json":
        print("[중요] JSON이 아닌 응답이에요. protobuf일 수 있어요. 디코더를 만들기 전에 이 출력을 그대로 공유해주세요(키는 출력되지 않아요).")
    print("[실패] 조회를 완료하지 못했어요. 위 상태와 reason을 확인해주세요.")
    return 1


def main(argv: list[str] | None = None, env: Mapping[str, str] | None = None, transport=None) -> int:
    parser = argparse.ArgumentParser(description="Safe Browsing hashes.search 수동 1회 확인 (실제 Google 호출)")
    parser.add_argument("--live", action="store_true", help="실제 Google 호출을 허용한다. 없으면 호출하지 않는다.")
    parser.add_argument("--timeout", type=float, default=10.0,
                        help=f"이번 확인의 제한 시간(초, 기본 10, 최대 {MAX_TIMEOUT:g}). 실제 지연을 재기 위해 앱 기본값보다 길다.")
    parser.add_argument("--probe", choices=["official-example"],
                        help="테스트 URL 대신 공식 예시 접두사 WwuJdQ 1개만 조회한다 (호출 1회).")
    # choices 밖의 값은 argparse가 호출 전에 거부한다 (종료 코드 2).
    parser.add_argument("--variant", choices=list(VARIANTS),
                        help="--probe official-example 전용 요청 변형. 한 번 실행에 하나, 호출 1회.")
    args = parser.parse_args(argv)
    if not args.live:
        return refuse("--live 옵션이 없어요. 실제 Google 호출은 --live를 붙여 직접 실행할 때만 해요.")
    if not 0 < args.timeout <= MAX_TIMEOUT:
        return refuse(f"--timeout은 0보다 크고 {MAX_TIMEOUT:g} 이하여야 해요.")
    if args.variant and args.probe != "official-example":
        return refuse("--variant는 --probe official-example과 함께만 쓸 수 있어요.")
    return asyncio.run(check(os.environ if env is None else env, args.timeout, transport, args.probe, args.variant))


if __name__ == "__main__":
    sys.exit(main())
