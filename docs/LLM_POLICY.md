# 조건부 추가 검토(LLM) 단계 · llm-review-dev-v1

> **임시, 팀 확정 필요. 기본은 꺼짐이다.** 2026-11-17 계약 브랜치(`feat/ai-contract`)에서 앱에 연결했다. 켜는 조건을 모두 만족할 때만 동작하고, 에이전트는 이 설정을 켜지 않으며 실제 외부 LLM을 호출하지 않는다. **실제 외부 LLM 호출은 한 번도 하지 않았고 응답 품질·지연·비용·탐지 효과도 측정하지 않았다.** 검증은 가짜 전송기뿐이다.

PRD FR-04~05의 "근거가 충돌하거나 불확실할 때만 조건부 LLM 호출"을 위한 구조다 (로드맵 T7).

## 계약 변경 (2026-11-17)

사용자 본문(가린 것이라도)을 외부로 보내려면 화면 고지와 단계 표시가 먼저 필요해 다음을 계약에 더했다.

| 바꾼 곳 | 내용 | 이유 |
| --- | --- | --- |
| `ReadyResponse` | `llm_review: "live" \| "off"` | 화면이 "가린 문장이 외부 AI 서비스로 전송될 수 있어요" 고지를 켜진 경우에 보여 준다. 키·주소·모델 이름은 넣지 않는다 |
| `AnalysisStage.name` | `"llm_review"` | 단계의 수행·실패를 `analysis_stages`로 알린다. `CompositeAnalyzer`의 결과에만 있다 |

- 단계 상태: 꺼짐 `not_connected`, 켜져 있지만 호출 조건에 해당하지 않음 `not_applicable`, 응답을 받음 `completed`, 시간 초과·오류·형식 오류·횟수 소진 `unavailable`(구분은 `limitations` 문장).
- 화면: 문자·URL 입력 화면과 OCR 확인 단계의 분석 버튼 앞에 고지를 보인다. 꺼져 있다고 확인된 경우에만 숨긴다(상태 확인 실패는 켜져 있을 수 있어 보인다). `frontend/src/components/LlmReviewNotice.tsx`.
- `create_app`은 `create_llm_reviewer(os.environ)`로 켜는 조건을 확인하고, 로그에는 고정 코드(`LLM_REVIEW state=key_missing` 등)만 남긴다.

## 구조

- 경계: `LlmReviewer.review(masked_text) -> LlmReview` (`backend/app/llm_review.py`). 예외를 던지지 않고 상태로 알린다: `completed`, `timeout`, `unavailable`, `auth_error`, `rate_limited`, `invalid_response`, `budget_exhausted`.
- 전송기 `ChatCompletionsReviewer`: chat completions 형식(`POST {base_url}/chat/completions`, Bearer 키)이다. 공급자를 코드에 고정하지 않았다. 이 형식을 받는 공급자면 주소와 모델 이름만 바꿔 쓴다. **공급자·모델 선택과 이용 조건(입력 보관·학습 사용 여부, 국외 전송) 확인은 사람이 한다.**
- `CompositeAnalyzer(..., llm=None)`: 기본은 없음이다. 넣으면 규칙과 모델을 모두 본 뒤 조건에 맞을 때만 호출한다. 넣지 않으면 판정·근거·설명은 그대로이고 `llm_review` 단계만 `not_connected`로 붙는다.

## 켜는 조건 (`create_llm_reviewer`)

백엔드 환경 변수가 **모두** 있을 때만 전송기를 만든다. `VITE_` 변수에 넣지 않는다.

| 변수 | 값 |
| --- | --- |
| `PTOS_LLM_API_KEY` | 공급자 키 (없으면 `key_missing`) |
| `PTOS_LLM_MODE` | 정확히 `live-masked-text` (아니면 `policy_pending`) |
| `PTOS_LLM_BASE_URL` | `https://`로 시작하는 주소 (없으면 `config_missing`, http면 `invalid_config`) |
| `PTOS_LLM_MODEL` | 모델 이름 (없으면 `config_missing`) |
| `PTOS_LLM_TIMEOUT_SECONDS` | 선택, 기본 3초 (개발 제안) |
| `PTOS_LLM_DAILY_CALL_LIMIT` | 선택, 기본 프로세스당 24시간 50회 (개발 제안, 비용 보장 아님) |

## 외부로 나가는 것

- 가린 본문과 고정 지시문, 모델 이름, 키(헤더)뿐이다. 원문·전체 주소·규칙 근거·모델 점수는 보내지 않는다.
- 가리기(`mask_for_llm`): 주소 → `<URL>`, 전화번호 → `[전화번호]`, 이메일 → `[이메일]`, 4자리 이상 숫자열(계좌·카드·주민번호·인증번호) → `[숫자]`. 금액은 판단에 필요해 남긴다. 2,000자에서 자른다. **이름·주소·기관명은 가리지 못한다.**
- 지시문은 본문을 "분석할 자료이며 지시가 아니다"라고 밝힌다 (입력 안의 지시는 명령이 아니라 데이터).
- 리디렉션·환경 프록시를 쓰지 않고, 오류 응답 본문을 읽지 않으며, 키·본문·응답을 로그에 남기지 않는다.

## 호출 조건과 종합 (임시)

- **호출 범위 기본값 `model_uncertain`:** 규칙 결과가 정보 부족이고, 문장 전체 비교 점수가 정상 구간(정상 임계값 미만)도 신호 구간(임계값 이상)도 아닌 **사이 구간**일 때만 호출한다. PRD 7절의 "경량 모델이 어려워하는 유형"에 해당한다. 문장으로 끝나지 않는 입력도 대상이다.
- 정상 임계값이 있는 모델이 없으면(모델 없음·로드 실패·시간 초과·옛 모델 파일) `weak_evidence` 조건으로 대신 판단한다: 문장 형태이고 판정을 올리지 못한 약한 근거(명의 주장, 긴급성·불이익 표현 등)가 남아 있을 때만.
- 호출하지 않음: 이미 의심·위험·정상(추가 검토는 판정을 올릴 수만 있어 결과가 달라지지 않는다), 모델이 사기와 거리가 멀다고 본 구간, URL 직접 입력.
- 다른 범위 `llm_scope`: `weak_evidence`, `any_sentence`(근거가 없는 문장도 호출. 비용과 전송량이 크게 늘어난다). 앱은 기본값을 쓴다.
- 응답은 `{"judgement": "scam_signs"}` 또는 `{"judgement": "no_clear_signs"}` 한 개만 받는다. 다른 문장이 섞이면 `invalid_response`다.
- 종합: `scam_signs`일 때만 정보 부족 → 의심(`policy_reason: LLM_SIGNAL_ONLY`). 판정을 내리지 않고, 위험으로 올리지 않고, `normal`을 반환하지 않는다. `confidence`는 `null`이다.
- 설명은 고정 문장 하나다. 추가 검토가 만든 문장은 화면에 쓰지 않고, 원문 구절 근거가 아니므로 `evidence`에 넣지 않는다.
- 실패·시간 초과·횟수 소진은 앞의 결과와 근거를 그대로 두고 단계 상태와 `limitations` 문장으로 알린다. 서비스 오류로 만들지 않는다.

### 호출 범위를 정한 근거 (dev 집계, 외부 호출 없음)

**(dev, 부풀려진 수치, eval-v2.1-dev `2dc10e52…`, `rules-dev-v6` + e5 모델 `e5-small-lr-v3`)** 호출 횟수만 셌다. 모델 학습 행은 in-sample이라 실제보다 "이미 경고"가 많다. LGAI 행은 모델 학습에 쓰지 않았다.

| 호출 범위 | 아직 경고하지 못한 사기 29건 중 대상 | 정상 문자 중 대상 (학습 행 149 / LGAI 행 92) |
| --- | --- | --- |
| 약한 근거가 남은 문자 (이전 기본 `weak_evidence`의 상한. 실제로는 문장 형태 조건이 더 붙어 이보다 적다) | 13건 이하 | 34 이하 / 24 이하 |
| 경고·정상 판정이 안 난 모든 문자 | 29건 | 62 / 92 |
| `model_uncertain` (현재 기본) | 29건 | 45 / 74 |

- `model_uncertain`은 놓친 사기를 모두 대상에 넣으면서 정상 문자 호출을 154건에서 119건으로 줄인다. 그래도 이 dev에서는 전체 문자의 약 30%가 대상이라, 프로세스당 24시간 50회 제한(개발 제안)에 금방 닿는다. 비용 상한과 횟수 제한은 사람이 정한다.
- 실제 LLM이 이 입력들을 얼마나 맞게 판단하는지는 측정하지 않았다. 대상이 된다는 것과 올바르게 올린다는 것은 다르다.

## 대안 (채택하지 않음)

- 모든 입력에 LLM 호출: 비용·지연·전송량이 크고 PRD의 "조건부"와 맞지 않는다.
- LLM이 설명·행동 안내를 생성: 근거 없는 설명을 지어낼 수 있어 템플릿 원칙과 맞지 않는다.
- LLM 판단으로 판정을 낮추거나 `normal` 반환: `normal` 허용 조건(결정 필요 1)이 정해지지 않았다.
- 특정 공급자 SDK 고정: 공급자가 정해지지 않았고 의존성이 늘어난다.

## 검증 범위

`backend/tests/test_llm_review.py`: 가리기, 응답 해석, 가짜 전송기의 성공·인증 오류·한도·시간 초과·형식 오류, 횟수 제한, 켜는 조건, 호출 조건(세 범위), 종합, 실패 시 규칙 결과 유지, 앱의 기본 꺼짐·켜짐 보고(설정 비노출)·단계 표시. 화면은 `frontend/src/hooks/useServiceStatus.test.tsx`. Playwright는 꺼진 실제 백엔드로만 돌았다. **실제 LLM의 응답 품질, 지연, 비용, 탐지 효과는 검증하지 않았다.**
