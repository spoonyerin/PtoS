# PtoS · 규칙 분석·URL 평판 어댑터·스크린샷 OCR

문자 또는 URL을 입력하면 FastAPI가 규칙 기반 위험 신호와 URL 형식·평판 연결 상태를 반환합니다. 스크린샷은 **미리보기 → OCR → 사용자 확인·수정 → 명시적인 확인 후 분석**을 거칩니다. OCR 직후 자동 위험 분석하지 않습니다. React/TypeScript 화면과 Python/FastAPI 분석기를 한 저장소에서 관리합니다.

> **경량 모델과 URL 평판 조회가 없는 규칙 기반 개발 버전**입니다. 신원·사기 여부를 확정하거나 안전을 보장하지 않습니다. `confidence`는 항상 `null`입니다. 실제 개인정보 대신 연습용 문장을 입력하세요.

이번 정책은 [RULE_POLICY.md](docs/RULE_POLICY.md)에 먼저 정리했습니다. 수치 점수나 PRD 확정 임계값을 만들지 않습니다. **현재는 `normal`을 반환하지 않습니다.** 규칙에 걸리지 않은 정상 안내문도 미구현 분석 때문에 **정보 부족**으로 표시하며 사기라고 단정하지 않습니다. 최종 MVP의 네 결과 열거형은 계약에 유지합니다.

실제 피싱 AI·경량 모델·LLM, 외부 URL 조회, DB, 배포, PWA 설치와 디자인 개편은 이번 범위에 없습니다. OCR에는 무료 로컬 Tesseract 5를 사용합니다. 최종 PRD 필수 범위와 미확정 사항은 [AGENTS.md](AGENTS.md)를 참고하세요.

이번 증분은 **Google Safe Browsing v5 hashes.search의 키 없는 어댑터**입니다. 정규화·해시·전체 해시 대조·응답 캐시·개발 호출 예산·종합 판정을 가짜 응답으로 검증합니다. **무료/무결제·할당량·필수 표시 조건은 정책 사이트 차단으로 미확인**이므로 실제 HTTP 전송기는 연결하지 않았습니다. 키가 있어도 `policy_pending`으로 외부 호출을 하지 않습니다. 키 발급·결제·추가 패키지 설치는 필요 없습니다. [공식 출처·확인 수준·정책·Windows 확인 순서](docs/SAFE_BROWSING.md)를 읽어주세요. 실제 화면의 평판은 계속 **미연결**입니다.

[이번 검증 기록](docs/SAFE_BROWSING_VALIDATION.md)은 가짜 평판 응답 테스트, 실제 한국어 OCR, 실제 Google API 미실행을 구분합니다.

**Windows Git Bash 사용자는 [설치·실행·화면 확인 순서](docs/WINDOWS_GIT_BASH.md)를 따라주세요.** Tesseract 설치와 한국어 데이터 준비가 추가되며, Windows 백엔드에서는 `--reload` 없이 실행합니다.

## 로컬에서 최신 PR 브랜치 실행하기

필요한 도구: **Python 3.12 이상**, **Node.js 22.12 이상**, Git. 검증 환경은 Python 3.12 / Node.js 24입니다. 기존 main의 앱을 실행 중이면 먼저 두 서버 터미널에서 각각 `Ctrl+C`로 종료하세요.

이미 저장소를 받았다면 저장소 최상위에서:

```bash
git fetch origin
git switch feat/safe-browsing-v5
git pull --ff-only
```

처음 받는다면:

```bash
git clone --branch feat/safe-browsing-v5 https://github.com/spoonyerin/PtoS.git
cd PtoS
```

두 개의 터미널을 열어 아래 서버를 각각 실행해두세요. 기존 버전과 새 버전의 프론트엔드/백엔드를 섞어 실행하지 마세요.

### 1. 백엔드

무료 CPU OCR인 **Tesseract 5** 실행 파일이 필요합니다. Linux(Debian/Ubuntu)는 `sudo apt-get update && sudo apt-get install -y tesseract-ocr`, macOS는 `brew install tesseract`로 설치할 수 있습니다. Codespaces는 Dockerfile에서 설치합니다. Windows 설치는 위 별도 안내를 따릅니다. GPU·유료 계정·API 키는 필요 없습니다.

macOS / Linux:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python scripts/setup_ocr.py
cd backend
../.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-access-log
```

Windows PowerShell:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r backend/requirements-dev.txt
$env:TESSERACT_CMD = 'C:\Program Files\Tesseract-OCR\tesseract.exe'
.\.venv\Scripts\python.exe scripts/setup_ocr.py
cd backend
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

### 2. 프론트엔드

두 번째 터미널의 저장소 최상위에서:

```bash
cd frontend
npm ci
npm run dev
```

API 키·DB·`.env`는 필요하지 않습니다. 설치 시 `setup_ocr.py`가 공식 한국어·영어 언어 데이터를 `.ocr/tessdata/`에 HTTPS로 다운로드하고 SHA-256을 검사합니다. 실행 중 외부 OCR 서비스에 연결하거나 모델을 자동 다운로드하지 않습니다. `TESSERACT_CMD`로 실행 파일, 선택적으로 `TESSDATA_PREFIX`로 언어 데이터 경로를 지정할 수 있습니다. 백엔드 주소를 바꾸는 경우에만 `frontend/.env.example`의 `API_PROXY_TARGET`을 사용하세요. 비밀값을 `VITE_` 변수에 넣지 마세요.

### 3. 브라우저로 확인

PC의 주소창에 `http://localhost:5173`을 입력합니다. 문자 입력 → **분석하기** → 근거 구절·이유·행동 안내를 확인하세요. `http://localhost:8000/docs`에서는 API 계약을 볼 수 있습니다.

| 입력 | 현재 기대 결과 | 확인할 점 |
| --- | --- | --- |
| `도서관은 내일 휴무입니다.` | 정보 부족 | 위험 요구 없음 + 모델 미구현. 정상 보증 아님 |
| `은행은 인증번호를 요구하지 않습니다.` | 정보 부족 | 부정 표현을 인증번호 요구로 만들지 않음 |
| `“은행입니다. 인증번호를 알려주세요.”는 사기 예시입니다.` | 정보 부족 | 교육 인용을 실제 요구로 채택하지 않음 |
| `인증번호를 알려주세요.` | 의심 | 짧아도 구체적 요구는 유지 |
| `앱을 설치해주세요.` | 의심 | 앱 설치 요구 구절 표시 |
| `은행 담당자입니다. 인증번호를 알려주세요.` | 위험 | 명의 주장 + 민감정보 요구 조합. 실제 사칭 검증은 아님 |
| `그거 지금 처리` | 정보 부족 | 발신자·요구 행동이 불명확한 단편 입력 |

### URL 직접 입력·메시지 추출 확인

입력 방식에서 **문자** 또는 **URL 직접 입력**을 선택합니다. URL은 실제로 열지 않으며, URL이 있다는 이유만으로 위험/정상을 판정하지 않습니다. 주소와 상태는 클릭할 수 없는 텍스트입니다.

| 입력 방식 | 확인할 입력 | 예상 결과 |
| --- | --- | --- |
| URL 직접 입력 | `https://예시.한국/공지` | 정보 부족, 형식 확인, ASCII 호스트 `xn--vv4b11d.xn--3e0b707e`, **평판 조회 미연결** |
| 문자 | `(HTTPS://EXAMPLE.INVALID:443), 다시 https://example.invalid/.` | 같은 URL 1개로 정리, 출현 2회, 구두점 경계 안내, 평판 미연결 |
| 문자 | `https://-bad.invalid/` | 정보 부족, 형식 확인 필요, 평판 조회 안 함 |
| URL 직접 입력 | `ftp://example.invalid/` 또는 `example.invalid` | 주소 형식 오류 안내. HTTP(S) 주소 한 개 필요 |
| 문자 | `은행입니다. https://예시.한국/공지. 인증번호를 알려주세요.` | 기존 규칙의 임시 위험 경고 + URL 형식/미연결을 별도로 표시 |

직접 입력은 앞뒤 공백만 제외하고 주소를 그대로 검사합니다. 메시지에서는 끝 구두점·짝이 없는 닫는 괄호를 제거하고 안내합니다. 한글 경로·국제화 도메인을 보존하며, 문장과 주소의 경계가 모호하면 원래 주소를 **URL 직접 입력**으로 확인하세요. 후보는 중복 제거 후 최대 10개이며 초과하면 자르지 않고 수정 요청을 표시합니다. 상세 기준은 [URL_POLICY.md](docs/URL_POLICY.md)에 있습니다.

내용을 수정하면 이전 결과는 지워집니다. 빈 입력·10,000자 초과는 제출하지 않습니다. 요청 중 중복 제출을 막고 서버 오류 후 입력을 유지합니다. 오류를 확인하려면 백엔드를 종료한 뒤 분석하고, 다시 시작해 재시도하세요. **서버 오류를 정보 부족 결과로 바꾸지 않습니다.**

### 스크린샷 OCR 확인

1. **스크린샷** → 파일 선택에서 `backend/tests/fixtures/korean-message.png`를 엽니다. 합성한 한국어 연습 이미지이며 JPG·PNG 한 장만 받습니다. 미리보기만으로 OCR/위험 분석하지 않습니다.
2. **이미지에서 글자 읽기 (OCR)**를 누릅니다. 추출 문자·URL 후보·경고를 원본과 비교하세요. 아직 분석 결과가 나오면 안 됩니다.
3. 전체 텍스트에서 문자와 URL을 수정할 수 있습니다. URL 후보는 수정 후 다시 추출하며 실제 주소 접속·평판 조회는 없습니다. 틀리거나 빠진 글자를 자동으로 복원하지 않습니다.
4. **추출한 문자와 URL을 원본과 비교해 확인했습니다.**를 체크한 뒤 **확인한 내용으로 분석하기**를 누릅니다. 수정·새 이미지·입력 방식 변경은 이전 확인과 분석 결과를 해제합니다.
5. 예를 들어 `은행입니다. 인증번호를 알려주세요. https://example.invalid/corrected`를 확인 후 제출하면 기존 규칙의 임시 위험 경고와 URL 평판 미연결을 따로 표시합니다. 잘린 내용을 확인할 수 없다면 체크하지 말고 재업로드하거나 문자로 직접 입력하세요.

개발 제한은 **10 MiB·2,000만 화소·엔진 실행 15초**, 브라우저 OCR 대기는 25초입니다. PRD 확정값이나 10초 제품 목표의 달성 보장이 아닙니다. 실제 형식·전체 디코딩·화소 수는 서버에서도 검사합니다. 빈 추출(`OCR_NO_TEXT`), 실패(`OCR_FAILED`), 시간 초과(`OCR_TIMEOUT`)는 서로 다른 오류이며 재업로드/직접 입력을 안내합니다.

이미지는 **현재 FastAPI 서버**로 전송됩니다. PC 실행이면 PC에서, 클라우드 실행이면 해당 클라우드에서 처리합니다. 별도 OCR 공급자에게 전송하지 않습니다. 서버의 원본·OCR 문자 임시파일, 원문 로그, DB/분석 이력 저장은 없습니다. 브라우저 확인 화면의 메모리에는 남고, 미리보기 Blob URL은 교체·해제 시 revoke합니다. 방식 비교·개발 제한·개인정보 경계·교체 인터페이스는 [OCR_POLICY.md](docs/OCR_POLICY.md)에 있습니다.

## Codespaces 또는 클라우드에서 확인

[Codespaces 단계별 안내](docs/CODESPACES.md)에 PR 브랜치 선택, 설치, **Tasks: Run Task → PtoS: 앱 실행**, **PORTS의 Private 5173 → Open in Browser**, 종료 순서를 정리했습니다. 8000 백엔드는 내부 프록시로 연결하므로 공개하지 않습니다. Codespace 생성·유료 배포·PR 병합은 사용자의 별도 선택이며 이 작업에서는 하지 않습니다.

이 채팅의 클라우드 localhost는 PC와 다르며 채팅 웹 시각화에 서버를 연결하는 기능은 없습니다. PC 실행이나 실제 IDE의 포트 전달로 확인하세요. Codespaces는 해당 환경의 전달 호스트만 허용합니다. `allowedHosts: true`로 호스트 검증을 해제하지 마세요.

## 분석 정책과 교체 지점

`backend/app/analyzers.py`의 `Analyzer.analyze(AnalysisInput) -> AnalysisResult`를 유지합니다. 현재 `RuleBasedAnalyzer`는 다음 모듈을 조합합니다.

- `urls.py`: 네트워크 없는 URL 검증·IDNA 정규화·중복 제거와 원문 위치 보존.
- `ocr.py`: 교체 가능한 `OcrEngine`, 실제 이미지 검증/EXIF 회전·제거, stdin/stdout 기반 Tesseract 어댑터. OCR API는 Analyzer를 호출하지 않음.
- `url_reputation.py`: 교체 가능한 `UrlReputationProvider`와 실제 연결을 보류하는 기본 어댑터. 백엔드의 키 유무만 확인하며 키 값은 보존하지 않음.
- `safe_browsing_urls.py` / `safe_browsing.py`: 로컬 URL 표현·SHA-256, 4바이트 prefix 전송 경계, 전체 해시 대조, 응답 TTL 캐시와 개발 예산. 테스트에서 가짜 전송기만 주입하며 실제 HTTP 전송기는 없음.
- `reputation_policy.py`: 검증된 전체 해시/위협 유형만 URL 원문 근거로 채택하고 문자 규칙과 종합. 결과 없음·오류는 규칙을 낮추거나 정상으로 승격하지 않음.
- `rule_detection.py`: 대상+긍정적 요구, 명의·긴급 표현, 부정/교육 인용 처리, 원문 근거.
- `rule_context.py`/`rule_policy.py`: 화자·인용·문단 경계를 구분하고 순수 명의 도입과 인접 직접 요구만 제한적으로 연결해 임시 판정. 반복 횟수나 숫자 점수를 합산하지 않음.
- `rule_templates.py`: 확인한 신호의 설명·행동만 선택. 기관 신원, 악성 URL, 외부 사실을 지어내지 않음.

향후 복합 Analyzer에서 실제 모델·평판 결과와 규칙 근거를 수집한 뒤 검증된 정책으로 종합할 수 있습니다. `analysis_stages`가 현재 미구현·생략 상태를 구분합니다. 규칙 부재를 정상 근거로 사용하지 않습니다. 정책의 한계와 조합은 [RULE_POLICY.md](docs/RULE_POLICY.md)를 읽고 변경하세요.

화면은 `frontend/src/components/`, 요청 상태는 `hooks/useAnalysis.ts`, HTTP·응답 검증은 `api/client.ts`입니다. 스타일은 이번 작업에서 변경하지 않았습니다. 근거 구절은 HTML/링크로 해석하지 않고 일반 텍스트로 표시합니다.

## API 계약 · 개발 버전 0.5

`POST /api/v1/analyses`는 `input_type` (`text`, `url`, `ocr_text`)과 `content`를 받습니다. `url`은 유효한 HTTP(S) 주소 한 개여야 하며, 문자에서는 URL 후보를 추출합니다. `ocr_text`에는 **`ocr_confirmed: true`가 필수**이며 확인 누락/false/1/문자열은 거부합니다. `content`는 공백만일 수 없으며 원문 기준 최대 10,000 유니코드 코드포인트입니다. 초과 입력은 자르지 않습니다. **기존 `demo_scenario`를 보내면 422**이므로 프론트엔드와 백엔드를 함께 업데이트하세요.

`POST /api/v1/ocr`는 `Content-Type: image/png` 또는 `image/jpeg`의 **바이너리 본문**을 받고 text/urls/warnings/engine/ocr_confidence(null)/request_id만 반환합니다. multipart 디스크 스풀을 피하는 메모리 스트리밍 방식이며 파일명은 받지 않습니다. `POST /api/v1/ocr/review`는 `{ "content": "수정 중인 문자" }`에서 URL 후보만 추출합니다. 두 API는 위험 분석과 평판 조회를 하지 않습니다. OCR 상태 확인은 별도 `scripts/setup_ocr.py`로 하며 기존 health/ready는 문자 분석기의 준비 상태입니다.

```json
{ "input_type": "text", "content": "은행 담당자입니다. 인증번호를 알려주세요." }
```

응답은 `request_id`, `risk_level`, `confidence: null`, `risk_factors`, `explanation`, `action_guidance`, `limitations`, `analysis_version: rules-reputation-dev-v1`, `analysis_mode: rules`, `is_demo: false`와 다음을 포함합니다.

- `evidence`: 코드·표시 이름·규칙 ID·`source: rule | url_reputation`·원문 구절·`start`/`end`. URL 근거는 검증된 전체 해시와 위협 유형 일치가 있어야 하며 기본 미연결 앱에서는 생성하지 않습니다. 좌표는 원문 유니코드 코드포인트의 시작 포함·끝 제외입니다. JS에서는 `Array.from(content).slice(start, end)`가 같은 구절이어야 합니다. 현재 화면은 좌표로 강조하지 않고 받은 구절을 그대로 표시합니다.
- `input_assessment`: `action_identified` / `sentence_present` / `fragment` / `url_only`와 이유. 글자 수만으로 충분성을 정하지 않습니다.
- `analysis_stages`: rules는 `completed`, lightweight_model은 `not_implemented`, url_reputation은 유효한 URL에 기본 어댑터를 쓰면 `not_connected`, 유효한 URL이 없으면 `not_applicable`입니다.
- `urls`: 원문/정규화 URL·ASCII 호스트, `validation_status: valid | invalid`, 형식 안내·경계 경고, 모든 `occurrences`(원문 구절·코드포인트 좌표), `reputation`을 포함합니다. 현재 유효 URL의 평판은 `not_connected`, 무효 후보는 `not_requested`이며 provider/checked_at은 null입니다. 형식 확인은 정상/안전 판정이 아닙니다.
- `policy_reason`: 어떤 임시 조합/보류 기준을 적용했는지 나타내는 개발용 식별자입니다. 확정 위험 점수가 아닙니다.

평판 계약에는 `auth_error`·`rate_limited`와 `reason`, `full_hash_verified`, `threat_types`, `cache_expires_at`, `cache_hit`을 추가했습니다. `unknown/no_match`는 안전 판정이 아니며 이 어댑터는 `benign`을 생성하지 않습니다. 테스트에서 검증한 전체 해시 위협 일치만 임시 위험 경고를 추가합니다. [종합 정책·상태 표](docs/SAFE_BROWSING.md)를 참고하세요.

`risk_level` 계약은 `normal | suspicious | dangerous | insufficient_information`을 유지하지만 현재 정책에서는 normal을 생성하지 않습니다. 지원하는 표현이 제한적이므로 우회 표현·복잡한 부정·인용·다른 대화 주체를 놓치거나 잘못 경고할 수 있습니다.

오류는 422(`INVALID_INPUT`/`INPUT_TOO_LONG`/`INVALID_URL`/`TOO_MANY_URLS`), 503(`ANALYSIS_UNAVAILABLE`), 서버 분석 5초 제한 초과 시 504(`ANALYSIS_TIMEOUT`)로 구분하며 `{ "error": { "code", "message", "retryable" }, "request_id" }` 형태입니다. 브라우저 대기 제한은 별도로 10초입니다. 정보 부족은 오류가 아닌 HTTP 200 분석 결과입니다.

상태 확인: `GET /api/v1/health/live`, `GET /api/v1/health/ready` (`mode: rules`). 입력·근거를 DB/파일/localStorage에 저장하거나 원문 로그로 남기지 않습니다. 응답은 `Cache-Control: no-store`입니다. URL을 직접 열거나 외부로 조회하지 않습니다. 현재 탭 메모리에는 입력과 결과가 남습니다. 공개 운영용 속도 제한·인증·요청 본문 바이트 제한은 아직 없으므로 개발 환경에서 사용하세요.

```bash
curl --fail http://127.0.0.1:5173/api/v1/analyses \
  -H 'Content-Type: application/json' \
  -d '{"input_type":"text","content":"은행입니다. 인증번호를 알려주세요."}'
```

## 테스트와 빌드

저장소 최상위에서:

```bash
cd backend
../.venv/bin/python -m pytest -q
RUN_REAL_OCR=1 ../.venv/bin/python -m pytest -q tests/test_ocr_real.py
../.venv/bin/python export_openapi.py --check
cd ../frontend
npm run api:check
npm test
npm run build
npx playwright install chromium
npm run test:e2e
```

이 클라우드에서는 마지막 두 명령 대신 시스템 Chromium으로 실행합니다.

```bash
PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH=/usr/bin/chromium npm run test:e2e
```

Playwright는 필요한 서버를 시작하고 자신이 시작한 서버만 종료합니다. 기본 포트의 기존 서버는 재사용하므로 반드시 최신 코드인지 확인하세요. 기존 문자/URL 회귀와 함께 OCR 미리보기·명시적 확인·수정 후 확인 해제·실패/빈 추출/시간 초과·취소를 확인합니다. 스크린샷은 `frontend/test-results/`의 `dangerous-desktop.png`, `insufficient-mobile.png`, `url-direct.png`, `ocr-review.png`이며 Git에서 제외합니다.

기본 pytest의 OCR은 **가짜 어댑터**로 제어 흐름을 검증하며 실제 인식 2개는 skip으로 표시합니다. 별도의 `RUN_REAL_OCR=1 ... tests/test_ocr_real.py`는 Tesseract로 고정 한국어 PNG/JPEG를 실제로 인식합니다. Playwright OCR 성공 시나리오 1개도 실제 서버·Tesseract이며 실패/빈 추출/시간 초과는 가짜 응답입니다. [실제 실행 관찰 기록](docs/OCR_VALIDATION.md)과 구분해 읽어주세요. 테스트는 규칙 회귀·연결 검증이지 실제 피싱 정확도·일반 OCR 정확도·최종 MVP 인수 검증이 아닙니다.

Windows에서는 Python 경로를 `..\.venv\Scripts\python.exe`로 바꾸세요. Playwright 자동 서버 실행은 POSIX 경로이므로 Windows에서는 두 서버를 먼저 실행하고 테스트하세요.

계약 변경 시 Pydantic(`backend/app/contracts.py`)을 수정한 뒤 아래 생성물을 함께 커밋합니다. 생성 파일을 직접 고치지 마세요.

```bash
cd backend
../.venv/bin/python export_openapi.py
cd ../frontend
npm run api:generate
npm run api:check
npm run build
```

## 자주 생기는 문제

- 예시 화면/422가 계속 보임: 브랜치와 서버 작업 폴더를 확인하고 두 서버를 종료·재시작한 뒤 브라우저를 새로고침하세요.
- 서버 연결 오류: 8000 백엔드 터미널과 Vite 프록시 로그를 확인하세요. 직접 백엔드 외부 URL이나 CORS 전체 허용을 추가하지 마세요.
- 포트 사용 중: 중복 실행한 PtoS 작업을 종료하세요. 테스트와 Codespaces는 5173/8000을 사용합니다.
- npm 캐시 쓰기 오류: `npm --cache /tmp/ptos-npm-cache ci`처럼 쓰기 가능한 경로를 지정하세요. TLS 검증을 해제하지 마세요.
- Codespaces 전달·종료 문제: [Codespaces 안내](docs/CODESPACES.md)를 참고하세요. 실제 Codespace 생성·외부 URL 접속과 현재 환경의 로컬 검증은 구분합니다.
