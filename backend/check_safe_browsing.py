"""Run from backend: python check_safe_browsing.py --live [--timeout 초]

Google Safe Browsing v5 hashes.search를 사람이 직접 한 번 확인하는 수동 스크립트다. 자동 테스트에 넣지 않는다.
- --live 옵션, GOOGLE_SAFE_BROWSING_API_KEY, PTOS_SAFE_BROWSING_MODE=live-noncommercial이 모두 있을 때만 호출한다.
- 사용자 입력은 받지 않는다. 아래 고정 테스트 URL의 해시 접두사만 1회 조회하고, 그 URL에는 접속하지 않는다.
- 키·접두사·전체 해시는 출력하지 않는다. 앱과 같은 정규화·해시·응답 대조(SafeBrowsingV5Provider)를 거친다.

테스트 URL 출처: Google 공식 GitHub 저장소 google/safebrowsing의 README(sblookup 예시,
https://github.com/google/safebrowsing). v4 참조 구현의 예시이며 v5 문서에서는 테스트 URL 목록을 찾지 못했다.
v5에서 이 URL이 위협 목록과 일치한다는 보장은 없다.
"""

import argparse
import asyncio
from collections.abc import Mapping
import os
import sys
import time

from app.safe_browsing import SafeBrowsingV5Provider, SearchResponse, TransportNetworkError, TransportResponseError, TransportTimeout
from app.safe_browsing_http import HttpxHashSearchTransport
from app.url_reputation import API_KEY_ENV, DEFAULT_TIMEOUT, LIVE_MODE, MODE_ENV, TIMEOUT_ENV
from app.urls import extract_urls

TEST_URL = "http://testsafebrowsing.appspot.com/apiv4/ANY_PLATFORM/MALWARE/URL/"
TEST_URL_SOURCE = "https://github.com/google/safebrowsing (README, sblookup 예시, v4 참조 구현)"
MAX_TIMEOUT = 30.0


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


async def check(env: Mapping[str, str], timeout: float, transport=None) -> int:
    key = env.get(API_KEY_ENV, "").strip()
    if not key:
        return refuse(f"{API_KEY_ENV}가 없어요. 백엔드 환경 변수로만 넣어주세요.")
    if env.get(MODE_ENV, "") != LIVE_MODE:
        return refuse(f"{MODE_ENV}={LIVE_MODE} 가 정확히 설정되어 있지 않아요.")
    value = extract_urls(TEST_URL, direct=True).records[0].value
    recorder = RecordingTransport(HttpxHashSearchTransport(key, timeout=timeout, transport=transport))
    # 이 스크립트 실행에서 호출은 최대 1회다.
    provider = SafeBrowsingV5Provider(recorder, per_minute=1, per_day=1, timeout=timeout)
    try:
        result = await provider.lookup(value)
    finally:
        await provider.aclose()

    print("Google Safe Browsing v5 hashes.search 수동 확인 (저장소 없는 실시간 모드)")
    print(f"테스트 URL: {TEST_URL}")
    print(f"테스트 URL 출처: {TEST_URL_SOURCE}")
    print("이 URL에는 접속하지 않았고, 4바이트 해시 접두사만 보냈어요.")
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
    args = parser.parse_args(argv)
    if not args.live:
        return refuse("--live 옵션이 없어요. 실제 Google 호출은 --live를 붙여 직접 실행할 때만 해요.")
    if not 0 < args.timeout <= MAX_TIMEOUT:
        return refuse(f"--timeout은 0보다 크고 {MAX_TIMEOUT:g} 이하여야 해요.")
    return asyncio.run(check(os.environ if env is None else env, args.timeout, transport))


if __name__ == "__main__":
    sys.exit(main())
