# Google Safe Browsing v5 · 연결 전 검토

검토 기준: PRD FR-03~06·개발설계서의 규칙/평판 분리와 개인정보 원칙. 이번 증분은 **키 없는 어댑터·가짜 응답 테스트**다. 실제 서비스의 탐지 성능, 무료 이용 자격, 약관 준수 완료를 의미하지 않는다. AWS·결제·계정 생성·키 발급은 수행하지 않았다.

## 공식 자료 확인 결과

확인 시도일: **2026-10-22 UTC**. Google 개발자 정책 사이트는 이 클라우드의 네트워크 프록시가 `403`으로 차단했다. Google 공식 GitHub API 정의와 공식 Go 참조 구현은 읽을 수 있었다. 따라서 API 규격과 이용 정책의 확인 수준을 구분한다.

| 확인할 사항 | 이번 확인 결과 | 공식 확인 위치 |
| --- | --- | --- |
| 비상업 학생 캡스톤의 무료 이용 자격·허용 범위 | **미확인**. 비상업이라는 이유만으로 무료 이용 승인을 받은 것으로 보지 않음 | [v5 시작](https://developers.google.com/safe-browsing/v5), [이용 약관](https://developers.google.com/safe-browsing/terms) |
| 결제수단 없이 API 활성화/키 사용 가능 여부 | **미확인**. 가입 화면을 열거나 카드 등록하지 않음 | [시작 안내](https://developers.google.com/safe-browsing/v5/get-started) |
| 무료 일/분당 할당량, 증액 조건, 초과 과금/자동 유료 전환 | **미확인**. 정확한 무료 호출 수를 제시하지 않음 | [Usage limits](https://developers.google.com/safe-browsing/v5/usage-limits) |
| 필수 사용자 경고·Google 출처/상표 표시 문구·위치 | **미확인**. 화면의 공급자명·오탐/미탐 주의 문구는 개발안이며 공식 준수 완료가 아님 | [Usage guidelines](https://developers.google.com/safe-browsing/v5/usage-guidelines) |
| 조회 데이터 보관·공유·삭제 조건 | **미확인**. 해시 접두사도 개인정보 비전송/익명성을 보장하지 않음 | 위 약관·[Google 개인정보처리방침](https://policies.google.com/privacy) |
| 인증 | 공식 Discovery 문서는 OAuth 토큰을 쓰지 않으면 API 키가 필요하다고 명시. 키의 무료 발급·무카드 이용과는 별개 | [공식 Discovery JSON](https://github.com/googleapis/google-api-python-client/blob/main/googleapiclient/discovery_cache/documents/safebrowsing.v5.json), revision `20251214` |
| `hashes.search` 요청·응답·캐시 | 공식 v5 정의에서 확인: 4바이트 접두사, 최대 1,000개/요청, URL 절차는 최대 30개, 전체 SHA-256 대조, 응답별 캐시 기간 | [공식 protobuf](https://github.com/googleapis/googleapis/blob/master/google/security/safebrowsing/v5/safebrowsing.proto), [REST 문서](https://developers.google.com/safe-browsing/reference/rest/v5/hashes/search) |

**결론: 무료·무결제·표시 조건이 확인되지 않아 실제 외부 연결을 보류한다.** 공식 정의의 1,000개는 요청 크기 제한이며 무료 일일 할당량이 아니다. GitHub 클라이언트의 Apache 라이선스도 API 서비스 무료 이용 조건을 대신하지 않는다.

## 현재 연결 경계

- `UrlReputationProvider` 계약을 유지한다. `SafeBrowsingV5Provider`는 주입받은 `HashSearchTransport`로만 동작한다. **현재는 실제 HTTP 전송 구현·운영 연결·활성화 스위치가 없다.** 테스트가 메모리의 가짜 전송기를 주입한다.
- 애플리케이션 기본 공급자는 `not_connected`다. 백엔드 환경변수 `GOOGLE_SAFE_BROWSING_API_KEY`가 없으면 `key_missing`, 있더라도 **`policy_pending`으로 통신하지 않는다.** 키만 넣고 재시작해서 외부 호출이 시작되는 일은 없다. 프론트엔드 변수·응답·로그에 키를 넣지 않는다.
- 미래 HTTP 전송기는 고정 `GET https://safebrowsing.googleapis.com/v5/hashes:search`에 반복 `hashPrefixes`(4바이트의 표준 Base64)만 전달해야 한다. 접두사는 URL 인코딩해야 하며 키는 백엔드에서 별도 인증 헤더로 전달하는 방식을 공식 문서로 재확인해야 한다. 전체 URL·도메인·입력·전체 해시는 요청에 넣지 않는다. Google은 연결 시 송신 IP·시각·접두사 등을 알 수 있으므로 익명성을 약속하지 않는다.
- 사용자 URL 접속·DNS·리디렉션·신규 검사 제출·인기 목록 기반 안전 판정·다른 공급자 전환·자동 재시도는 없다.
- `.env` 자동 로딩은 하지 않는다. `backend/.env.example`은 비밀값 없는 변수 이름 안내다. 지금은 키를 발급하거나 채팅에 공유할 필요가 없다.

## URL 절차와 제한

`safe_browsing_urls.py`는 입력용 `urls.py`와 별개다. 기존 입력 검증을 느슨하게 하지 않는다. 정규화/해싱은 로컬 메모리에서 수행하고 원문 표시와 코드포인트 좌표를 보존한다.

1. 앞뒤 공백 정리, literal 탭/CR/LF 제거, literal fragment 제거 후 퍼센트 인코딩을 반복 해제한다. 디코딩 중 나타난 `#`는 fragment로 버리지 않고 다시 escape한다.
2. 호스트 소문자·반복/양끝 점 정리, IDNA UTS #46, IPv4 변형/IPv6 표기를 처리하고 포트·스킴을 해시 표현에서 제외한다.
3. 경로의 반복 슬래시·`.`/`..`를 정리한다. 제어/비ASCII 바이트와 `#`, `%`를 대문자 hex로 escape한다. 쿼리의 순서·값은 보존한다.
4. 호스트는 전체 호스트와 마지막 최대 5개 label부터 2개 label까지의 suffix(최대 5개 표현), IP는 하나만 생성한다. 경로는 루트+첫 3개 디렉터리 prefix+전체 경로+전체 경로/쿼리로 최대 6개다. 중복 제거 후 최대 30개를 SHA-256하고 4바이트 prefix만 조회 경계에 넘긴다.
5. 응답의 32바이트 해시를 **로컬의 전체 해시**와 비교한다. prefix만 같은 충돌은 `unknown`이다. 지원되지 않는 위협 유형/속성은 해당 detail을 무시한다. `CANARY`와 `FRAME_ONLY`도 이 독립 URL 경고에 사용하지 않는다.

규격 근거: [URL 처리 문서](https://developers.google.com/safe-browsing/v5/urls-hashing) 본문은 이번 환경에서 미확인. 알고리즘과 회귀 벡터는 [Google 공식 Go 참조](https://github.com/google/safebrowsing/blob/bbf0d20d26b32d99fd21664677fe31ee9f0f66e3/urls.go)·[테스트](https://github.com/google/safebrowsing/blob/bbf0d20d26b32d99fd21664677fe31ee9f0f66e3/urls_test.go)를 교차 확인했다. 이 참조는 v4이므로 v5 API 정의의 최대 30개에 맞춰 host/path 개수를 제한했다. 실제 연결 전에 최신 v5 URL 문서와 추가 상호운용성 검증이 필요하다. 브라우저 내장 Safe Browsing과 완전히 같은 범위를 구현했다고 주장하지 않는다.

입력은 기존 HTTP(S) 한정·10,000 코드포인트·URL 후보 10개 제한을 유지한다. 중첩 escape 1,024회 초과·처리 불가 주소는 `unavailable/normalization_failed`로 보류하며 `no_match`로 바꾸지 않는다. 이 자원 제한은 개발 제안이다. URL/원문을 캐시 키·로그·디스크로 보존하지 않는다.

## 응답 상태·캐시·예산

| 상태 / reason | 의미 |
| --- | --- |
| `malicious / full_hash_match` | 전체 해시 + 지원하는 위협 detail 일치. `full_hash_verified: true`와 `threat_types` 제공 |
| `unknown / no_match` | 200 응답을 받았지만 유효한 전체 해시 위협 일치 없음. **안전 판정 아님** |
| `unknown / unsupported_details` | 일치 해시의 유형/속성을 현재 URL 경고에 적용할 수 없음 |
| `auth_error / authentication_failed` | HTTP 401/403. 원문 오류 본문·키는 반환하지 않음 |
| `rate_limited / provider_rate_limit` | HTTP 429. 자동 재시도/증액 없음 |
| `rate_limited / local_limit` | 로컬 개발 예산 소진. Google 할당량과 구분 |
| `timeout / request_timeout` | 큐 대기 포함 제한 초과. 취소·잠금 해제 |
| `unavailable` | 통신/프로토콜/정규화/캐시 용량 장애. 404도 결과 없음으로 처리하지 않음 |

일부 음성 캐시가 다른 접두사 응답을 기다리는 동안 만료되면 `cache_expired_during_lookup`으로 보류한다. 다음 시도는 만료분만 다시 조회하며 만료 자료로 조회 완료를 주장하지 않는다.

- 공식 응답 `cacheDuration`을 각 조회 접두사의 양성·음성 결과 모두에 적용한다. 값이 누락/잘못되면 장애다. TTL을 추정·고정하거나 음성 TTL을 임의로 연장하지 않는다. 만료 자료는 재사용하지 않는다.
- 캐시는 프로세스 메모리에 prefix·반환된 전체 해시·위협 유형·시각만 보유한다. 호스트·경로·키·원문을 보존하지 않는다. 미만료 캐시를 쫓아내고 다시 조회하지 않도록 용량 부족이면 새 호출을 보류한다. 재시작하면 사라진다.
- 동시 중복은 잠금으로 합치고 실제 전송은 동시에 1개다. 개발 기본 예산은 프로세스당 **분당 2회·rolling 24시간 100회·캐시 2,048 prefix·큐 포함 1초**다. 이는 **PRD/Google 확정 제한이 아닌 개발 제안**이다. 실패 시도도 횟수에 포함하며 캐시 읽기는 호출 수를 쓰지 않는다. 현재 앱의 실제 호출 수는 항상 0이다.
- 복수 URL은 각각 기한을 적용해 한 주소 지연으로 문자 규칙 결과 전체가 사라지지 않게 한다. 부분 캐시의 유효한 전체 해시 일치는 새 경로의 조회 불가와 무관하게 유지한다.
- 현재 단일 Windows 프로세스 개발용이다. 향후 여러 서버/worker 배포 전에는 공급자 약관에 맞는 캐시 지속성·전역 예산/동시성·백오프를 설계해야 한다. 현재 기본값을 운영 무료 사용 보장으로 쓰지 않는다.

## 종합 판정 · rules-reputation-dev-v1

T4(2026-10-27)에서 문자 규칙이 `rules-dev-v3`(임시)로 바뀌어 `RuleBasedAnalyzer`의 `analysis_version`은 `rules-reputation-dev-v2`다. T5에서 API 응답은 모델 종합을 거쳐 `rules-model-dev-v1`이 됐다([MODEL_POLICY.md](MODEL_POLICY.md)). 평판 종합 방식은 아래와 같고 바뀌지 않았다.

| 확인한 근거 | 개발용 결과 |
| --- | --- |
| 기존 문자 조합의 위험/의심 + 평판 미연결·결과 없음·오류·시간 초과 | 기존 위험/의심과 정확한 원문 근거 유지. 평판 실패는 별도 상태 표시 |
| 유효한 전체 해시 위협 일치 + 문자 근거 유무 무관 | `dangerous` 경고. 문자 근거를 보존하고 URL 출현 구절에 `URL_REPUTATION_MATCH / source: url_reputation` 추가 |
| 교육 인용 안의 URL이 위협 목록과 일치 | URL에 대한 경고만 추가. 교육 문장의 발신자를 범죄자라고 만들지 않음 |
| URL 존재·형식 확인·접두사 충돌·미지원 detail·결과 없음만 있음 | 기존 정책 유지. 경고 요구가 없으면 `insufficient_information`. `normal` 승격 없음 |
| 단순 `malicious` 문자열뿐이며 전체 해시 검증/위협 유형 없음 | 종합 판정 위험 근거로 채택하지 않음 |

위 정책은 개발 제안이다. `dangerous`는 목록 일치에 근거한 위험 가능성 경고이며 사기 확정이 아니다. 기관 신원, 메시지 발신자, 송금 요구 등 입력에 없는 사실은 추가하지 않는다. `confidence`는 **null**, 모델/LLM은 미구현이다. `benign`은 기존 공급자 교체 계약 호환용으로 남기지만 이 어댑터는 생성하지 않으며 정상 근거로 쓰지 않는다. 공급자별 상태·출처·시각·캐시 여부는 주소와 함께 일반 텍스트로만 표시한다. 정확한 필수 경고/상표 준수 확인은 실제 연결의 선행 조건이다.

## 무료 조건이 계속 불명확할 때의 로컬 대안

**Phishing.Database의 수동 승인된 로컬 snapshot**을 대안으로 제안한다. [공식 프로젝트](https://github.com/Phishing-Database/Phishing.Database) README는 feeds를 무료로 제공한다고 명시하고, [LICENSE](https://github.com/Phishing-Database/Phishing.Database/blob/master/LICENSE)와 README의 License 절은 MIT 사용·복사·수정·배포를 무료로 허용한다. 확인일은 위와 같다. API 계정·키·결제수단 없이 파일을 로컬에서 조회할 수 있는 방식이다. 저작권/라이선스 고지 보존이 필요하고 데이터는 AS IS이며 정확도·최신성 보장이 없다.

채택 시 **URL이 포함된 active 목록**의 버전/다운로드일/체크섬·라이선스를 기록한 뒤 로컬 해시 색인을 만들고 별도 `UrlReputationProvider`로 연결한다. 목록 없는 주소·만료 snapshot은 unknown이지 안전이 아니다. 사용자의 입력 URL을 목록 제공자에 전송하거나 대상 URL에 접속하지 않는다. 목록 다운로드는 공개 데이터 갱신이며 사용자 URL 제출과 구분한다. 이번에는 라이선스/README만 읽었고 **위협 목록 다운로드·로컬 공급자 구현·자동 전환은 하지 않았다.** 이를 선택하려면 별도 승인이 아니라 다음 구현 방향을 사용자가 선택하면 된다.

## Windows에서 지금 확인하기

기존 OCR 설치는 유지한다. 두 서버를 `Ctrl+C`로 종료하고 Git Bash의 저장소 최상위에서:

```bash
git fetch origin
git switch main
git pull --ff-only
./.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
```

기존 Git Bash 첫 터미널의 `TESSERACT_CMD` 설정을 유지하고:

```bash
cd backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

두 번째 Git Bash에서 `cd frontend`, `npm ci`, `npm run dev`를 차례로 실행한다. 브라우저에서 **http://localhost:5173**을 연다.

1. URL 직접 입력 `https://예시.한국/공지` → **정보 부족 / 형식 확인 / 평판 조회 미연결**. 클릭 가능한 링크가 없어야 한다.
2. 문자 `은행입니다. 인증번호를 알려주세요. https://example.invalid/test` → 기존 **위험** 근거 유지 + 평판 미연결. 실제 Google 악성 탐지가 아니다.
3. 기존 한국어 합성 이미지로 OCR → 수정 → 확인 체크 → 분석 순서가 유지되어야 한다. OCR/수정 미리보기 API는 계속 평판 조회를 하지 않는다.
4. 가짜 응답 어댑터 테스트: 저장소 최상위에서 `cd backend` 후 `../.venv/Scripts/python.exe -m pytest -q tests/test_safe_browsing.py tests/test_safe_browsing_urls.py`. 실제 Google 계정/키 없이 악성 일치·접두사 충돌·빈 결과·인증·한도·시간 초과·캐시를 검증한다. 사용자 화면에 가짜 평판을 켜는 운영용 데모 경로는 없다.

**키가 필요한 시점의 첫 단계:** 우선 PC 브라우저로 위 Google 공식 이용 조건·Usage limits·Usage guidelines를 확인한다. 무료 비상업 캡스톤 허용, 결제수단 없음, 자동 과금 없음, 정확한 할당량과 표시 요건을 확인할 때까지 키 발급/실연결로 진행하지 않는다. 결제 연결 화면이 필수이면 중단하고 로컬 대안을 선택한다. 준비가 확인된 다음 작업에서 API 제한·키 발급·백엔드 환경변수 설정을 한 단계씩 안내한다. 키는 PC의 백엔드에서만 직접 입력하며 **채팅·Git·화면·스크린샷에 공유하지 않는다.** 현재는 키를 준비할 필요가 없다.
