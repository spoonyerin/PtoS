# 경량 모델 연결과 임시 종합 정책 · rules-model-dev-v1

> **임시, 팀 확정 필요.** 모델 신호의 반영 방식, 임계값 기준, 학습 라벨 매핑은 중간점검 시연을 위한 개발용 정책이다. PRD가 확정한 판정 경계·정확도·신뢰도·임계값이 아니다 (AGENTS.md "결정 필요" 1~3).

## 범위

- 모델: TF-IDF 문자 n-gram(`char_wb`, 2~4) + 로지스틱 회귀 하나. 중간점검의 기준선이다. KoELECTRA 등 트랜스포머 비교(T5c)는 중간점검 이후로 미룬다.
- 목적: 규칙과 경량 모델이 서버에서 함께 도는 흐름을 보여주는 것. **성능 주장이 아니다.**
- 학습 데이터는 합성 중심(KR-MOB-SMISHING v1, CC BY-NC 4.0)이라 모델 파일을 저장소에 커밋하지 않는다.

## 구조

- `CompositeAnalyzer`(`backend/app/analyzers.py`)가 `RuleBasedAnalyzer`(규칙 + URL 평판)와 모델을 **둘 다 실행**하고 종합한다. 규칙에 걸려도 모델을 생략하지 않는다 (short-circuit 금지).
- 모델 경계는 `TextRiskModel.score(text) -> float`(`backend/app/model_adapter.py`)이다. 테스트는 가짜 모델을 쓴다.
- 모델 입력은 원문에서 URL 구간을 `<URL>`로 바꾼 문장이다(`prepare_model_text`). 학습과 추론이 같은 함수를 쓴다. URL 직접 입력에는 모델을 쓰지 않는다.
- 추론은 스레드에서 돌리고 제한 시간은 1초다(개발 제안). 전체 분석 제한(5초)보다 짧아 모델이 느려도 504가 아니라 규칙 결과로 응답한다. 시간 초과 시 스레드는 끝까지 돌지만 결과는 버린다.

## 모델 파일과 로드

- 서버 시작(`create_app`) 시 한 번 로드한다. 백엔드 환경 변수 `PTOS_MODEL_PATH`에 모델 폴더(manifest.json + model.joblib)를 준다. 없으면 모델 단계를 끈다.
- 로드 전 확인: 경로가 저장소 안이면 거부, manifest 형식(같은 폴더의 파일 이름, 0~1 임계값), 모델 파일 SHA-256이 manifest와 일치, manifest의 scikit-learn 버전이 서버와 같음.
- joblib(pickle)은 로드할 때 코드를 실행할 수 있다. SHA 확인은 파일 바뀜을 잡을 뿐 신뢰할 수 없는 파일을 막지 못하므로 **직접 학습한 파일만** 쓴다.
- 로드 실패는 서버를 멈추지 않는다. 로그에는 고정 코드(예: `MODEL_SHA256_MISMATCH`)만 남기고 경로·예외 문자열은 남기지 않는다.

## 임시 종합 정책

| 규칙 결과 | 모델 신호 있음 (점수 ≥ 임계값) | 모델 신호 없음 · 단계 실패 |
| --- | --- | --- |
| 정보 부족 | **의심** (`policy_reason: MODEL_SIGNAL_ONLY`) | 정보 부족 유지 |
| 의심 | 의심 유지 (`policy_reason` 유지) | 유지 |
| 위험 | 위험 유지 (`policy_reason` 유지) | 유지 |

- 모델은 판정을 올릴 수만 있고 내리지 않는다. `normal`은 반환하지 않는다. `confidence`는 `null`이고 점수는 응답에 넣지 않는다.
- `MODEL_SIGNAL_ONLY`는 "규칙에 행동 요구 조합은 없고 모델 신호만 있다"는 뜻이다. 명의 주장처럼 단독으로 판정을 올리지 않는 약한 규칙 근거가 함께 있어도 같은 코드를 쓴다.
- 모델 신호는 원문 구절 근거가 아니므로 `evidence`·`risk_factors`에 넣지 않는다. 기존 `FactorCode`로는 표현할 수 없다.
- 설명: 신호가 있으면 아래 문장을 붙인다. 정보 부족에서 의심으로 올릴 때는 정보 부족 머리말을 이 문장으로 바꾸고, 약한 규칙 설명은 뒤에 남긴다.
  > 문장 전체가 사기 문자에서 자주 보이는 표현과 비슷해요. 어떤 부분 때문인지는 알 수 없고, 사기라고 확정한 것은 아니에요.
- 행동 안내는 새 문장을 만들지 않는다. 규칙 근거가 없으면 기존 기본 두 줄이다.
- 화면 문장에는 "경량 모델", "학습 자료" 같은 내부 용어를 쓰지 않는다.

## 모델 단계 표시 (계약 변경 없음)

| 상황 | `analysis_stages`의 `lightweight_model` | limitations 문장 |
| --- | --- | --- |
| 신호 있음 / 없음 | `completed` | 참고용 비교 안내 / 안전 보증 아님 |
| `PTOS_MODEL_PATH` 없음 | `not_connected` | 기능이 꺼져 있어 규칙 결과만 표시 |
| 로드 실패 (저장소 안 경로, SHA·버전 불일치 등) | `unavailable` | 준비하지 못해 규칙 결과만 표시 |
| 시간 초과 / 추론 오류 | `unavailable` | 제때 끝나지 않음 / 문제가 생김, 규칙 결과만 표시 |
| URL 직접 입력 | `not_applicable` | 주소만 입력해 비교하지 않음 |

로드 실패·시간 초과·오류의 구분은 limitations 문장으로만 한다. 기계가 읽는 상태는 모두 `unavailable`이다.

**알려진 한계 (중간점검 이후 B안 검토):** 모델이 함께 돌아도 응답의 `analysis_mode`는 계약상 `"rules"`로 남는다. 상태 구분도 위처럼 거칠다. B안은 `analysis_mode`에 `"rules+model"`, 단계 상태에 `timeout`·`load_failed`를 추가하는 계약 변경이며 OpenAPI·생성 타입·`client.ts`·프론트 테스트를 함께 바꿔야 한다.

## 학습과 임계값 (`backend/train_model.py`)

- 라벨(D1-a): 사기 = `suspicious` + `dangerous`, 정상 = `normal`. `insufficient_information` 라벨과 URL 입력 행은 학습에서 뺀다.
- **split=dev 행만** 학습·임계값 결정에 쓴다. test 행은 CSV 형식 검사로 읽은 직후 버리고 건수만 기록한다.
- dev 안에서 `campaign_id` 기준 층화 그룹 교차검증(`StratifiedGroupKFold`, 기본 5 fold, 시드 고정)으로 out-of-fold(OOF) 점수를 낸다. 같은 campaign은 한 fold에만 들어간다.
- **임계값 기준(임시, 팀 확정 필요):** OOF 점수에서 expected=normal 행이 모델 신호로 표시되는 경우 0건을 지키면서 사기 재현율이 최대인 값, 곧 normal 최고 점수보다 큰 사기 점수 중 가장 낮은 값이다. 규칙이 이미 의심으로 판정한 normal 행도 신호를 내지 않아야 하므로, 판정이 올라가는지로 따지는 것보다 엄격하다. manifest에 `threshold_status: "provisional-dev-cv"`로 기록한다. 그런 값이 없으면 `threshold_found: false`이고 서버는 그 모델로 신호를 내지 않는다.
- 같은 OOF 점수로 임계값을 골랐으므로 OOF 지표도 낙관적이다. normal 표본이 적으면 임계값이 크게 흔들린다.
- 최종 모델은 dev 전체로 다시 학습한다. 그래서 하네스로 dev를 다시 평가하면 in-sample이며 비교에 쓰지 않는다. dev 비교는 `train-report.md`의 OOF 결과를 쓴다.
- manifest에는 모델 버전, 시드, 설정, fold 수, 평가 CSV SHA-256, 모델 파일 SHA-256, 코드 커밋·작업 트리 상태, 라이브러리 버전, 건수, 임계값 상태가 들어간다. 원문은 없다.

## 의존성

`scikit-learn==1.9.1`과 모델 파일 호환을 위해 `numpy==2.5.4`, `scipy==1.18.1`, `joblib==1.6.0`을 고정했다(`backend/requirements.txt`). 버전을 올리면 기존 모델 파일은 로드를 거부하므로 다시 학습한다.
