# URL 평판 어댑터 검증 기록

## T6 실제 연결 (2026-10-28)

정책·켜는 조건·표시 방식은 [SAFE_BROWSING.md](SAFE_BROWSING.md)를 본다. 자동 테스트와 실제 Google 호출을 구분해 적는다. 어느 것도 탐지 성능 검증이 아니다.

### 자동 테스트 (실제 Google 호출 없음)

환경: Windows 11 / Git Bash / Python 3.13.15 / Node 24.16.0. 기준: 4단계 커밋 `8619c4f`의 작업 트리.

| 확인 | 결과 | 범위와 한계 |
| --- | --- | --- |
| 백엔드 `pytest -q` | 724 passed, 2 skipped(실제 OCR) | 평판은 가짜 전송기와 `httpx.MockTransport`만 사용. `tests/conftest.py`가 루프백 외 연결 시도를 막고 실패시킴 |
| 전송기 | 요청 모양(쿼리는 `hashPrefixes`만, padding 없는 표준 Base64, `+`·`/` 퍼센트 인코딩, `alt`·JSON Accept 없음, 키는 헤더만), protobuf 200(일치·결과 없음·충돌·모르는 enum·CANARY/FRAME_ONLY), JSON 호환, 지원하지 않는 형식·크기 초과·해석 실패, 401/403/429/5xx/400/404/302, 시간 초과, 네트워크 오류, 키 비노출 | 가짜 응답 |
| protobuf 디코더 | 인코딩 규칙대로 조립한 고정 바이트(바이트마다 주석), 비정상 24가지, 모든 잘림 위치, 무작위 5,000개 | protobuf 라이브러리와 대조하지 않음 |
| 켜는 조건 | 키·모드·시간 제한 조합, 꺼짐이면 전송기 미생성, ready `live/off`, 켜진 앱의 실제 연결 시도를 테스트 차단 장치가 잡는지 | 가짜 키 |
| 수동 확인 스크립트 | 거부 조건, 1회 호출, 변형 4종의 요청 모양, 오류 분류 출력, 키가 URL에 들어가는 변형의 stdout·stderr·DEBUG 로그 비노출, protobuf 구조 요약 | 가짜 응답 |
| `export_openapi.py --check`, `npm run api:check` | 통과 | 4단계에서 ready 응답 계약 변경 후 생성물 재생성 |
| `npm test` | 10 files, 65 passed | 전송 안내 켜짐/꺼짐/확인 실패, Google 표기 대상 구분 |
| `npm run build` | 통과 | |
| Playwright | 29 passed | 실제 FastAPI(평판 꺼짐). ready 켜짐·실패와 평판 결과는 브라우저 라우트의 가짜 응답. OCR 성공 1개는 실제 Tesseract |
| 실제 OCR(`RUN_REAL_OCR=1`) | 2단계에서 2 passed, 4단계에서는 재실행 안 함 | OCR 코드 변경 없음 |

### 실제 Google 호출 (사용자가 직접 실행, 결과는 사용자 보고)

사용자 PC에서 `backend/check_safe_browsing.py`로 실행했다. 키는 백엔드 환경 변수로만 넣었고 출력에는 키·접두사·해시가 없다. 실행 한 번에 호출은 1회이며, 실제 호출은 모두 **8회**다.

| 회차 | 실행과 요청 모양 | 결과 | 응답 시간 |
| --- | --- | --- | --- |
| 1 | 기본 실행. 앱 전송기 형태(`alt=json`, `Accept: application/json`, 헤더 키), 테스트 URL 접두사 10개 | 400 (`http_error`) | 1,282ms |
| 2 | 1회차와 같은 실행, 키를 다시 넣고 반복 | 400 (`http_error`) | 1,112ms |
| 3 | 오류 분류 출력을 추가한 뒤 기본 실행(1회차와 같은 요청 모양) | 400 `INVALID_ARGUMENT`. message에 Base64·API key 언급 없음 | 409ms |
| 4 | `--probe official-example`. 공식 예시 접두사 `WwuJdQ` 1개, 앱 전송기 형태 | 400 `INVALID_ARGUMENT` | 497ms |
| 5 | `--variant official-exact`. 쿼리 키, `alt` 없음, `hashPrefixes`만 | 200 `application/x-protobuf`, 본문 49바이트 | 541ms |
| 6 | `--variant no-alt`. 헤더 키, `alt` 없음 | 200 `application/x-protobuf`, 본문 49바이트 | 494ms |
| 7 | `--variant no-alt`, 직접 디코더로 구조 확인 | 200, `full_hashes` 1개, 상세 2개(`MALWARE`, `POTENTIALLY_HARMFUL_APPLICATION`), `cache_duration` 300s | 433ms |
| 8 | 기본 실행. B단계 앱 전송기(헤더 키, `alt`·JSON Accept 없음), 테스트 URL 접두사 10개 중 2개에 `+`·`/` 포함 | 200 `application/x-protobuf`, `malicious / full_hash_match`, `MALWARE` | 548ms |

- 실행하지 않은 변형: `key-query`, `padded`.
- 400의 원인이 `alt=json`인지 `Accept: application/json`인지는 구분하지 못했다. 둘을 함께 뺀 요청(5·6회차)만 성공을 확인했다.
- 결론: 응답은 protobuf다. 표준 Base64(`+`·`/` 퍼센트 인코딩, padding 없음) 접두사가 받아들여졌다(8회차). 키는 헤더(6·7·8회차)와 쿼리(5회차) 모두 200이었고, 앱은 헤더를 쓴다.
- 응답 시간: 1·2회차 1,112~1,282ms, 3~8회차 409~548ms. 앱 제한 1초는 유지한다(사용자 결정).
- 테스트 URL은 v4 참조 구현 예시(google/safebrowsing README)이며 이번 v5 호출에서 일치했다. 1건의 일치는 정규화·해시 절차 전체의 상호운용성이나 탐지 범위 검증이 아니다.
- 앱 화면에서 켜진 상태로 실제 조회한 확인은 하지 않았다.

## 키 없는 어댑터 단계 (2026-10-22)

실행일: 2026-10-22 UTC. Linux 클라우드 / Python 3.12 / Node 24 / 시스템 Chromium. Windows 로컬 실행은 이번 환경에서 수행하지 않았다.

| 확인 | 결과 | 범위와 한계 |
| --- | --- | --- |
| 백엔드 pytest | 336 passed, 실제 OCR 2 skipped | 평판은 전부 가짜 전송기. 정규화/표현/해시, prefix 충돌, 전체 해시/위협 detail, 오류, TTL, 동시성, 캐시 용량, 호출 예산, 종합 판정, 로그 비노출·기본 앱 비접속 |
| 실제 한국어 Tesseract 별도 실행 | 2 passed | 고정 합성 PNG/JPEG. 일반 OCR 정확도 검증 아님 |
| OpenAPI export `--check`, TS `api:check` | 통과 | 계약 원본과 생성물 일치 |
| 프론트엔드 Vitest | 43 passed | 신규 평판 상태·출처·캐시·비링크 표시 포함 |
| TypeScript + Vite build | 통과 | 스타일 변경 없음 |
| Playwright 실제 브라우저 | 25 passed | 기존 문자/URL/API·OCR 확인 흐름 + 가짜 평판 화면 5개. OCR 성공 1개는 실제 Tesseract. OCR 오류와 평판 응답은 가짜 |
| API 키 없는 실제 Google 요청 | **미실행** | 기본 앱에 HTTP 전송기가 없고 실제 호출 0회 |
| 키를 이용한 실제 Google 요청 | **미실행** | 계정/키 발급·결제·사용자 URL 전송 없음 |
| Google 무료/무결제/할당량/필수 표시 정책 | **미확인** | 공식 정책 사이트 접근 시 프록시 403. 실제 연결 선행 조건 |

마지막 검토에서 조회한 링크에 대해 문자 템플릿이 “조회하지 않았다”고 말하지 않도록 문구를 중립화했다. 이에 대한 백엔드 회귀와 영향을 받는 문자/평판 브라우저 시나리오 15개를 다시 실행해 통과했다. 모든 평판 검증은 탐지 정확도·공식 API 상호운용성·약관 준수 완료와 구분한다. 실제 연결 전 최신 v5 URL 규격/표시 문구·키 제한·할당량·백오프·배포 시 캐시/전역 예산을 확인해야 한다.

실행 명령은 [README](../README.md), 정책·공식 출처와 Windows 확인 입력은 [SAFE_BROWSING.md](SAFE_BROWSING.md)를 따른다.
