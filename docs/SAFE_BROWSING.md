# Google Safe Browsing v5 · URL 평판 조회

검토 기준: PRD FR-03~06·개발설계서의 규칙/평판 분리와 개인정보 원칙. T6(2026-10-28)에서 `hashes.search`의 실제 HTTP 전송기와 켜는 조건을 구현했다. **기본값은 꺼짐**이며, 키와 명시적 모드가 모두 있을 때만 외부로 조회한다. 실제 호출 결과와 자동 테스트 범위는 [SAFE_BROWSING_VALIDATION.md](SAFE_BROWSING_VALIDATION.md)에 구분해 적었다. 탐지 성능 검증이 아니다.

## 이용 범위 (비상업)

URL 평판 조회는 Google Safe Browsing API(hashes.search)를 사용한다. 이 API는 비상업적 용도로만 사용할 수 있으며, 상업적 목적에는 Web Risk API를 사용해야 한다. 본 프로젝트는 캡스톤 개발·검증·시연 목적의 비상업적 사용이며, 팀원과 평가자에게만 접근을 허용하고 공개 운영 서비스로 배포하지 않는다. 상업화할 경우 Web Risk API 등 상업용 수단과 이용 조건을 재검토한다.

## 고지

**Google Safe Browsing의 보호는 완벽하지 않습니다. 안전한 사이트가 위험한 사이트로 잘못 표시되거나, 위험한 사이트를 찾아내지 못할 수 있습니다.** Google은 정확하고 최신의 정보를 제공하려 하지만 그 정보가 완전하고 오류가 없다고 보장하지 않는다. 이 앱의 결과는 안전을 보장하지 않는다.

출처: [Permitted Use](https://developers.google.com/safe-browsing/reference/Appropriate.Usage) (2026-10-28 확인). 같은 문서의 다른 요구사항과 이 앱의 대응은 아래 "화면·응답 표시"에 적었다.

## 공식 자료와 확인 수준

확인일 2026-10-28. "사용자 확인"은 사용자가 Google 콘솔·공식 문서에서 직접 확인해 알려준 내용이다.

| 항목 | 결과 | 확인 방법·출처 |
| --- | --- | --- |
| 비상업 용도 한정, 상업용은 Web Risk | 확인 | [Permitted Use](https://developers.google.com/safe-browsing/reference/Appropriate.Usage), 사용자 확인 |
| 결제수단 없이 키 발급·API 사용 설정 | 확인. 키 발급 시 결제수단 요구 없음, 프로젝트에 결제 계정 없음 | 사용자 확인 (콘솔) |
| 키 제한 | API 제한: Safe Browsing API 1개. 애플리케이션 제한: 없음 (AWS 배포 시 서버 고정 IP 제한 예정, HANDOVER T8) | 사용자 확인 (콘솔) |
| 할당량 | 콘솔 기본 할당량은 하루 10,000회 수준. **hashes.search가 어느 할당량 항목에 해당하는지는 미확정** | 사용자 확인 (콘솔) |
| 필수 표기 | Google 근거 경고에 "Advisory provided by Google"과 Advisory 링크, 한정 표현, 오탐·미탐 고지, Google 외 근거에는 Google 표기 금지 | [Permitted Use](https://developers.google.com/safe-browsing/reference/Appropriate.Usage) |
| 요청 형식 | `GET /v5/hashes:search`, 본문 없음, 반복 `hashPrefixes`(4바이트, base64, 최대 1,000개, 보통 30개 이하) | [REST hashes.search](https://developers.google.com/safe-browsing/reference/rest/v5/hashes/search), [safebrowsing.v5.json](https://github.com/googleapis/google-api-python-client/blob/main/googleapiclient/discovery_cache/documents/safebrowsing.v5.json) revision `20251214` |
| 인증 | `key` 쿼리 또는 `X-Goog-Api-Key` 헤더 | safebrowsing.v5.json, [System parameters](https://docs.cloud.google.com/apis/docs/system-parameters) |
| 응답 형식 | 개요 문서: 응답 본문은 protobuf. 실제 호출: `alt` 없이 요청하면 `application/x-protobuf`, `alt=json`과 `Accept: application/json`을 함께 보내면 400 `INVALID_ARGUMENT` | [개요](https://developers.google.com/safe-browsing/reference), 수동 호출(VALIDATION 문서) |
| 응답 필드 | SearchHashesResponse 1 `full_hashes`, 2 `cache_duration`(Duration) / FullHash 1 `full_hash`, 2 `full_hash_details` / FullHashDetail 1 `threat_type`, 2 `attributes` | [safebrowsing.proto](https://github.com/googleapis/googleapis/blob/master/google/security/safebrowsing/v5/safebrowsing.proto), [duration.proto](https://github.com/protocolbuffers/protobuf/blob/main/src/google/protobuf/duration.proto) |
| 저장소 없는 실시간 모드 | 로컬 DB 없이 매번 hashes.search 조회, 전체 해시 메모리 캐시 | [No-Storage Real-Time Mode](https://developers.google.com/safe-browsing/reference/No.Storage.Real.Time.Mode) |

## 켜는 조건

백엔드 환경 변수로만 설정한다. `.env` 자동 로딩은 없고, `VITE_` 변수나 프론트엔드에는 넣지 않는다. 키는 채팅·코드·로그·문서·커밋·`.env` 파일에 쓰지 않는다.

| 환경 변수 | 값 | 의미 |
| --- | --- | --- |
| `GOOGLE_SAFE_BROWSING_API_KEY` | 사용자가 발급한 키 | 없으면 `not_connected / key_missing` |
| `PTOS_SAFE_BROWSING_MODE` | 정확히 `live-noncommercial` | 다른 값(공백·대소문자 차이 포함)이거나 없으면 키가 있어도 `not_connected / policy_pending`, 외부 호출 없음 |
| `PTOS_SAFE_BROWSING_TIMEOUT_SECONDS` | 선택, 기본 `1` | URL 하나당 큐 대기 포함 제한(개발 제안). 0보다 크고 전체 분석 제한(5초)보다 작아야 하며, 아니면 `not_connected / invalid_config`로 꺼진 상태 유지 |

- 서버 시작 시 한 번만 판단한다. 바꾸면 서버를 재시작한다(Windows는 `--reload` 금지). 켜지면 "lookups are ON" 경고 로그 한 줄을 남긴다(키 없음).
- `GET /api/v1/health/ready`의 `url_reputation`이 `live` 또는 `off`를 알려준다. 키·시간 제한·공급자 상태는 넣지 않는다. 화면은 이 값으로 전송 안내를 켜고 끈다.
- 실제 조회는 `create_app`이 앱당 공급자 하나로만 만든다. 평가 하네스·학습·측정 스크립트와 직접 만든 `RuleBasedAnalyzer()`는 항상 미연결이다.
- 자동 테스트는 외부 호출을 하지 않는다. pytest는 `backend/tests/conftest.py`가 키·모드 변수를 지우고 루프백 외 연결 시도를 막고 실패시킨다. Playwright는 백엔드에 `PTOS_SAFE_BROWSING_MODE=''`를 주고, 재사용된 서버가 켜져 있으면 실패하는 확인 테스트가 있다.

## 요청과 응답 처리

- **보내는 것:** `GET https://safebrowsing.googleapis.com/v5/hashes:search?hashPrefixes=…` (반복). 접두사는 4바이트 SHA-256 앞부분의 **표준 Base64, padding 없음**이며 `+`·`/`는 `%2B`·`%2F`로 인코딩한다. 키는 `X-Goog-Api-Key` 헤더로만 보낸다. `alt`와 JSON `Accept` 헤더는 보내지 않는다.
- **보내지 않는 것:** URL 원문, 호스트, 경로, 입력 문자, 전체 해시. 사용자 URL에 접속·DNS 조회·리디렉션 추적을 하지 않는다. 리디렉션은 따라가지 않고, 환경의 프록시·`.netrc`를 쓰지 않는다(`trust_env=False`).
- **익명성 한계:** 켜면 Google은 송신 IP·시각·접두사를 알 수 있다. 해시 접두사도 익명성을 보장하지 않는다.
- **응답:** `application/x-protobuf`는 직접 디코더(`backend/app/safe_browsing_proto.py`, protobuf 패키지 미사용)로 REST JSON과 같은 모양으로 바꾼 뒤 기존 `parse_response`로 검증한다. `application/json`은 호환용으로 받는다. 그 외 형식, 1 MiB(개발 제안) 초과, 해석 실패는 `invalid_response`다. 오류 응답 본문은 읽지 않는다.
- **공식 절차와 다른 점:** 공식 No-Storage 절차는 오류 시 SAFE를 반환하지만, 이 앱은 오류·결과 없음을 안전으로 바꾸지 않는다.

## URL 절차와 제한

`safe_browsing_urls.py`는 입력용 `urls.py`와 별개다. 기존 입력 검증을 느슨하게 하지 않는다. 정규화/해싱은 로컬 메모리에서 수행하고 원문 표시와 코드포인트 좌표를 보존한다.

1. 앞뒤 공백 정리, literal 탭/CR/LF 제거, literal fragment 제거 후 퍼센트 인코딩을 반복 해제한다. 디코딩 중 나타난 `#`는 fragment로 버리지 않고 다시 escape한다.
2. 호스트 소문자·반복/양끝 점 정리, IDNA UTS #46, IPv4 변형/IPv6 표기를 처리하고 포트·스킴을 해시 표현에서 제외한다.
3. 경로의 반복 슬래시·`.`/`..`를 정리한다. 제어/비ASCII 바이트와 `#`, `%`를 대문자 hex로 escape한다. 쿼리의 순서·값은 보존한다.
4. 호스트는 전체 호스트와 마지막 최대 5개 label부터 2개 label까지의 suffix(최대 5개 표현), IP는 하나만 생성한다. 경로는 루트+첫 3개 디렉터리 prefix+전체 경로+전체 경로/쿼리로 최대 6개다. 중복 제거 후 최대 30개를 SHA-256하고 4바이트 prefix만 조회 경계에 넘긴다.
5. 응답의 32바이트 해시를 **로컬의 전체 해시**와 비교한다. prefix만 같은 충돌은 `unknown`이다. 지원되지 않는 위협 유형/속성은 해당 detail을 무시한다. `CANARY`와 `FRAME_ONLY`도 이 독립 URL 경고에 사용하지 않는다.

규격 근거: 알고리즘과 회귀 벡터는 [Google 공식 Go 참조](https://github.com/google/safebrowsing/blob/bbf0d20d26b32d99fd21664677fe31ee9f0f66e3/urls.go)·[테스트](https://github.com/google/safebrowsing/blob/bbf0d20d26b32d99fd21664677fe31ee9f0f66e3/urls_test.go)를 교차 확인했다(v4). v5 API 정의의 최대 30개에 맞춰 host/path 개수를 제한했다. [URL 처리 문서](https://developers.google.com/safe-browsing/v5/urls-hashing) 본문과의 상호운용성은 테스트 URL 1건의 실제 일치 외에는 검증하지 않았다. 브라우저 내장 Safe Browsing과 같은 범위를 구현했다고 주장하지 않는다.

입력은 기존 HTTP(S) 한정·10,000 코드포인트·URL 후보 10개 제한을 유지한다. 중첩 escape 1,024회 초과·처리 불가 주소는 `unavailable/normalization_failed`로 보류하며 `no_match`로 바꾸지 않는다. 이 자원 제한은 개발 제안이다.

## 응답 상태

| 상태 / reason | 의미 |
| --- | --- |
| `malicious / full_hash_match` | 전체 해시 + 지원하는 위협 detail 일치. `full_hash_verified: true`와 `threat_types` 제공 |
| `unknown / no_match` | 200 응답, 유효한 전체 해시 위협 일치 없음. **안전 판정 아님** |
| `unknown / unsupported_details` | 일치 해시의 유형/속성(모르는 번호, CANARY, FRAME_ONLY 등)을 경고에 쓸 수 없음 |
| `not_connected / key_missing`, `policy_pending`, `invalid_config` | 키 없음 / 모드 미설정 / 시간 제한 설정 오류. 외부 호출 없음 |
| `not_connected / not_configured` | 공급자 없이 직접 만든 분석기(평가·스크립트). 외부 호출 없음 |
| `auth_error / authentication_failed` | HTTP 401/403. 오류 본문·키는 반환하지 않음 |
| `rate_limited / provider_rate_limit` | HTTP 429. 자동 재시도/증액 없음 |
| `rate_limited / local_limit` | 로컬 개발 예산 소진. Google 할당량과 구분 |
| `timeout / request_timeout` | 큐 대기 포함 제한 초과 또는 HTTP 시간 초과 |
| `unavailable / network_error` | 연결·읽기 등 네트워크 오류 |
| `unavailable / server_error` | HTTP 5xx |
| `unavailable / http_error` | 그 밖의 HTTP 상태(400, 404, 302 등). 404도 결과 없음으로 처리하지 않음 |
| `unavailable / invalid_response` | 지원하지 않는 형식, 크기 초과, protobuf·JSON 해석 실패, 필수 필드 누락 |
| `unavailable / transport_error`, `normalization_failed`, `cache_capacity`, `cache_expired_during_lookup` | 기타 전송 예외 / 정규화 불가 / 캐시 용량 / 대기 중 음성 캐시 만료 |

어느 실패도 이미 확보한 규칙·모델 근거와 판정을 지우지 않는다. `analysis_stages`의 `url_reputation`은 하나라도 조회를 끝내지 못하면 `unavailable`, 모두 끝나면 `completed`, 미연결이면 `not_connected`, 유효 URL이 없으면 `not_applicable`이다. URL별 상세 상태는 `urls[].reputation.status/reason`에 있다.

## 캐시·호출 예산

- 응답 `cacheDuration`을 각 조회 접두사의 양성·음성 결과 모두에 적용한다. 값이 누락/잘못되면 장애다. TTL을 추정·고정하거나 음성 TTL을 연장하지 않는다(공식 문서는 결과가 비었을 때 24시간 이내 연장을 허용하지만 사용하지 않는다). 만료 자료는 재사용하지 않는다.
- 캐시는 프로세스 메모리에 prefix·반환된 전체 해시·위협 유형·시각만 보유한다. 호스트·경로·키·원문을 보존하지 않는다. 미만료 캐시를 쫓아내고 다시 조회하지 않도록 용량 부족이면 새 호출을 보류한다. 재시작하면 사라진다.
- 동시 중복은 잠금으로 합치고 실제 전송은 동시에 1개다. 개발 기본 예산은 프로세스당 **분당 2회·rolling 24시간 100회·캐시 2,048 prefix·큐 포함 1초**다. **이 값들은 PRD/Google 확정 제한이 아니며 Google 할당량도 아닌 개발 제안이다.** 실패 시도도 횟수에 포함하며 캐시 읽기는 호출 수를 쓰지 않는다.
- 1초 제한은 유지한다(사용자 결정, 2026-10-28). 실제 응답 시간은 첫 두 호출 1.1~1.3초, 이후 409~548ms였다. 첫 연결이 느리면 `timeout`이 될 수 있다.
- 단일 Windows 프로세스 개발용이다. 여러 서버/worker 배포 전에는 캐시 공유·전역 예산/동시성·백오프를 설계해야 한다.

## 화면·응답 표시

- **출처 구분(현재 계약으로 가능, 계약 변경 없음):** `evidence[].source`가 `rule`과 `url_reputation`을 나누고, Google 출처 여부는 `urls[].reputation.provider == "google_safe_browsing_v5"`와 occurrence 좌표가 같은지로 판단한다. 모델 신호는 `evidence`가 아니다. 한계: `explanation`은 규칙 문장과 URL 문장을 이어 붙인 문자열이라, Google 표기는 설명문이 아니라 URL 결과와 URL 근거 옆에 붙인다. `Evidence`에 공급자 필드를 넣는 계약 변경은 중간점검 이후 검토 항목이다(HANDOVER).
- **Google 표기:** 공급자가 Google이고 `malicious`이며 전체 해시가 검증된 URL과 그 근거에만 "Advisory provided by Google (Google 제공 경고)"와 고정 링크 `https://developers.google.com/safe-browsing/v4/advisory`를 붙인다. 규칙·모델 근거에는 붙이지 않는다. 링크 경로는 Permitted Use 문서가 가리키는 v4 경로이며, v5 전용 Advisory 페이지 유무는 미확인이다.
- **한정 표현과 고지:** "위험한 사이트일 수 있다는 보고가 있어요", "Google은 정확한 정보를 제공하려 하지만, 위험한 사이트를 놓치거나 안전한 사이트를 위험으로 잘못 표시할 수 있어요. 안전을 보장하지 않아요."
- **전송 안내:** 켜져 있거나 상태를 확인하지 못하면 문자·URL 입력과 OCR 확인 단계의 분석 버튼 앞에 "URL 확인 기능이 켜져 있어요. 주소를 그대로 보내지 않고, 주소에서 만든 일부 정보(해시)만 Google로 전송돼요."를 보인다. 꺼짐이 확인되면 숨긴다. OCR 업로드 화면에는 없다(OCR은 Google로 보내지 않음).
- 사용자 URL은 링크로 만들지 않는다. 화면의 외부 링크는 고정 Advisory 주소뿐이다.
- 결과 제목 "위험"은 규칙과 평판을 합친 앱의 판정이다. Google 판정처럼 읽히는지는 사용성 검토에서 확인한다.

## 종합 판정 · rules-reputation-dev-v2

T4(2026-10-27)에서 문자 규칙이 `rules-dev-v3`(임시)로 바뀌어 `RuleBasedAnalyzer`의 `analysis_version`은 `rules-reputation-dev-v2`다. T5에서 API 응답은 모델 종합을 거쳐 `rules-model-dev-v1`이 됐다([MODEL_POLICY.md](MODEL_POLICY.md)). 평판 종합 방식은 아래와 같고 T6에서 바뀌지 않았다.

| 확인한 근거 | 개발용 결과 |
| --- | --- |
| 기존 문자 조합의 위험/의심 + 평판 미연결·결과 없음·오류·시간 초과 | 기존 위험/의심과 정확한 원문 근거 유지. 평판 실패는 별도 상태 표시 |
| 유효한 전체 해시 위협 일치 + 문자 근거 유무 무관 | `dangerous` 경고. 문자 근거를 보존하고 URL 출현 구절에 `URL_REPUTATION_MATCH / source: url_reputation` 추가 |
| 교육 인용 안의 URL이 위협 목록과 일치 | URL에 대한 경고만 추가. 교육 문장의 발신자를 범죄자라고 만들지 않음 |
| URL 존재·형식 확인·접두사 충돌·미지원 detail·결과 없음만 있음 | 기존 정책 유지. 경고 요구가 없으면 `insufficient_information`. `normal` 승격 없음 |
| 단순 `malicious` 문자열뿐이며 전체 해시 검증/위협 유형 없음 | 종합 판정 위험 근거로 채택하지 않음 |

위 정책은 개발 제안이다. `dangerous`는 목록 일치에 근거한 위험 가능성 경고이며 사기 확정이 아니다. 기관 신원, 메시지 발신자, 송금 요구 등 입력에 없는 사실은 추가하지 않는다. `confidence`는 **null**이다. `benign`은 공급자 교체 계약 호환용이며 이 어댑터는 생성하지 않는다.

## 수동 확인 (실제 호출은 사람이 직접)

`backend/check_safe_browsing.py`는 자동 테스트에 넣지 않는 1회 확인 스크립트다. `--live` 옵션, 키, `PTOS_SAFE_BROWSING_MODE=live-noncommercial`이 모두 있어야 호출하며, 실행 한 번에 호출은 최대 1회다. 사용자 입력은 받지 않는다.

- 기본 실행: 고정 테스트 URL `http://testsafebrowsing.appspot.com/apiv4/ANY_PLATFORM/MALWARE/URL/`의 접두사만 앱과 같은 경로로 조회한다. 이 URL에는 접속하지 않는다. 출처는 Google 공식 GitHub [google/safebrowsing README](https://github.com/google/safebrowsing)의 sblookup 예시(v4 참조 구현)이며, v5 문서에서는 테스트 URL 목록을 찾지 못했다.
- `--probe official-example [--variant no-alt|key-query|padded|official-exact]`: 공식 개요 예시 접두사 `WwuJdQ` 1개로 요청 모양을 바꿔 진단한다. key-query·official-exact는 키가 URL에 들어가므로 URL·예외 메시지를 출력하지 않고 httpx 로그를 막는다.
- 출력: 응답 시간, HTTP 상태, Content-Type, protobuf 구조(개수·길이·위협 유형), 판정, 오류 분류(`error.status`, `details[].@type`·`reason`, `fieldViolations.field`, message 안의 Base64/API key 언급 여부). 키·접두사·전체 해시·원본 바이트·오류 message 원문은 출력하지 않는다.

Git Bash, 저장소 최상위 기준:

```bash
read -rs GOOGLE_SAFE_BROWSING_API_KEY && export GOOGLE_SAFE_BROWSING_API_KEY
export PTOS_SAFE_BROWSING_MODE=live-noncommercial
cd backend
../.venv/Scripts/python.exe check_safe_browsing.py --live
unset GOOGLE_SAFE_BROWSING_API_KEY PTOS_SAFE_BROWSING_MODE
```

`read -rs`는 키를 화면과 셸 기록에 남기지 않는다. 확인 후 `unset`하지 않으면 같은 셸에서 띄운 서버도 실제 조회가 켜진다.

## Windows에서 앱으로 확인하기

- 기본(꺼짐): 키·모드 없이 서버를 띄우면 화면 상단에 "URL 평판 조회는 꺼져 있으며", URL 결과에 **평판 조회 미연결**이 보이고 전송 안내는 없다.
- 켜서 확인(실제 호출 발생): 위 `read -rs`·`export` 두 줄을 실행한 셸에서 백엔드를 시작한다. 상단 문구가 "켜져 있지만"으로 바뀌고 입력 화면에 전송 안내가 보인다. 테스트 URL을 분석해 Google 표기가 붙은 위험 가능성 경고가 나오는지 확인한다. 2026-10-28에 사용자가 문자 입력으로 수동 확인했다: 전송 안내가 분석 버튼 위에 보였고, 첫 조회는 시간 초과(1초)로 규칙 결과만 나왔으며, 약 1분 뒤 두 번째 조회에서 `malicious / full_hash_match`(`MALWARE`)와 Google 근거에만 Advisory 링크가 표시됐다([VALIDATION](SAFE_BROWSING_VALIDATION.md)). 자동 테스트가 아닌 수동 관찰이다. 끝나면 서버를 끄고 `unset`한다.

## 로컬 대안 (채택 안 함)

[Phishing.Database](https://github.com/Phishing-Database/Phishing.Database)(MIT)의 수동 승인 snapshot을 로컬 해시 색인으로 조회하는 별도 `UrlReputationProvider`를 대안으로 검토했다. 다운로드·구현하지 않았다. 목록에 없는 주소·만료 snapshot은 unknown이지 안전이 아니다.

## 미확정

- hashes.search가 해당하는 할당량 항목과 정확한 한도, 초과 시 동작.
- v5 전용 Advisory 페이지 유무와 표기 위치의 최종 검토.
- `alt=json`과 JSON `Accept` 중 어느 쪽이 400의 원인인지(둘을 함께 뺀 요청만 성공 확인).
- 다중 프로세스·AWS 배포 시 캐시·예산 공유, 키 애플리케이션 제한(서버 고정 IP).
- 한국 스미싱 URL에 대한 탐지 범위(측정 안 함).
