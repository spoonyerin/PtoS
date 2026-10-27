# 평가 하네스

고정 평가셋 CSV를 분석기로 판정해 4단계 지표를 Markdown 리포트로 낸다 (로드맵 T2).
탐지 성능은 이 하네스로 고정 평가셋을 측정한 결과로만 주장한다. 단위 테스트(`tests/test_evaluation.py`)는 가짜 합성 샘플로 코드 동작만 확인하며 그 수치는 탐지 성능이 아니다.

## 평가 데이터 보관

평가 데이터는 저장소에 커밋하지 않는다. 실제 수신 문자는 개인정보를 담을 수 있다.

- **저장소 밖, 동기화되지 않는 폴더에 둔다.** 이 저장소가 OneDrive·Dropbox·iCloud 같은 동기화 폴더 안에 있으면, `.gitignore`로 git에서 빼도 파일은 클라우드로 올라간다. 예: `C:/ptos-eval/`(Windows), `~/ptos-eval/`(동기화 대상이 아닌 홈 하위).
- `--data`로 그 경로를 넘긴다. 저장소 안으로 복사하지 않는다.
- 리포트(`--output`)도 같은 폴더에 둔다. 리포트에는 원문이 없지만 id와 판정 목록이 들어간다.
- 안전장치로 `.gitignore`에 `/eval-data/`, `/eval-reports/`를 넣었다. 실수로 저장소 최상위에 두었을 때 커밋만 막을 뿐이며, 동기화 폴더 문제는 해결하지 않는다.

## 평가셋에 넣기 전 개인정보 가리기

평가셋에 넣기 전에 사람이 직접 개인정보를 가린다. 하네스는 가리기를 하지 않는다.

- 가릴 대상: 이름, 전화번호, 계좌번호, 카드번호, 주민등록번호, 주소, 이메일, 인증번호, 수신자를 특정할 수 있는 주문·송장 번호.
- 판정에 필요한 형태는 남긴다. 예: `홍길동` → `[이름]`, `010-1234-5678` → `[전화번호]`, `123456` 인증번호 → `[인증번호]`. 정규식만으로 자동 치환하면 피싱 신호(예: "인증번호를 알려주세요"의 문맥)까지 지울 수 있으니 결과를 눈으로 확인한다.
- URL은 판정 근거가 될 수 있다. 수신자를 식별하는 경로·쿼리(토큰, 전화번호)만 가린다. 평가 중에도 URL에 접속하지 않으며, 하네스는 평판 조회를 미연결 어댑터로 고정한다.
- 원천 데이터의 이용 조건(재배포, 해외 업로드 허용 범위)은 데이터마다 따로 확인한다 (HANDOVER 6절).

## CSV 스키마

UTF-8 CSV(Excel의 UTF-8 BOM 허용). 컬럼은 HANDOVER 4절과 같다. 모든 컬럼이 헤더에 있어야 한다.

| 컬럼 | 규칙 |
| --- | --- |
| `id` | 비어 있지 않고 중복 없음. 리포트에서 행을 가리키는 유일한 값이다. 원문 일부를 id로 쓰지 않는다. |
| `text`, `url` | 둘 중 **정확히 하나**만 채운다. `text`는 `input_type=text`, `url`은 `input_type=url`로 분석한다. 둘 다 있으면 형식 오류다. |
| `expected_level` | `normal` / `suspicious` / `dangerous` / `insufficient_information` |
| `label_reason` | 판정 근거와 경계 사례 여부. 리포트에 넣지 않는다. |
| `source`, `is_synthetic` | 출처와 합성 여부. `is_synthetic`은 `true/false`(`1/0`, `yes/no` 허용). |
| `campaign_id` | 같은 캠페인·변형·도메인 묶음. dev와 test에 같은 값이 있으면 리포트가 누출 경고를 낸다 (값은 표시하지 않음). |
| `split` | `dev` / `test`. 최종 테스트셋은 정책·임계값 조정에 쓰지 않는다. |
| `review_status` | 검수 합의 상태. 허용 값은 정해지지 않았다. |

4단계 라벨은 검수 지침에 따라 직접 부여한다. 원천 데이터의 이진 라벨을 자동 변환하지 않는다.
형식 오류가 있으면 리포트를 만들지 않고 행 번호와 컬럼만 알린다 (셀 값은 출력하지 않음).

## 원천 데이터 변환: KR-MOB-SMISHING v1 (라벨링 전용)

`scripts/convert_kr_mob_smishing.py`는 KR-MOB-SMISHING v1 zip(CC BY-NC 4.0, 합성)의 `message_samples_used[].text` 104건을 **라벨링 전용** CSV로 바꾼다. 저장소에는 스크립트만 두고, zip과 출력물은 저장소·OneDrive 밖에 둔다.

```bash
# 저장소 최상위에서
./.venv/Scripts/python.exe -I scripts/convert_kr_mob_smishing.py --zip C:/_Coding/ptos-eval/KR-MOB-SMISHING-100-v1.zip --out-dir C:/_Coding/ptos-eval
```

- 출력 1 `<out-dir>/kr-mob-smishing-v1.labeling.csv`: 위 스키마 + `watermark_removed` 열(하네스는 추가 열을 무시한다). `expected_level`·`split`·`label_reason`·`review_status`는 비어 있고 `is_synthetic=true`, `source`에 데이터셋 이름·라이선스·변경 사항을 적는다. 본문은 맨 앞 `[TRAINING]`과 바로 뒤 공백 1칸만 제거했다.
- 출력 2 `<out-dir>/mapping/kr-mob-smishing-v1.case_type_mapping.csv`: `id`·`campaign_id` → 원래 `incident_id`·`case_type`, 시드, 원본 zip SHA-256. **라벨링 중에는 열지 않는다.** 원래 `case_type`(malicious / benign_lookalike / benign)은 4단계 라벨이 아니며 자동 변환하지 않는다.
- `incident_id`·파일명에 MAL/BEN이 들어 있어 라벨이 드러나므로, 라벨링 파일의 `id`(`KMS-001`~)·`campaign_id`(`C-001`~)·행 순서는 고정 시드로 섞은 불투명 값이다. 같은 incident의 본문은 같은 `campaign_id`다. 같은 zip·시드면 같은 결과가 나온다.
- zip은 풀지 않고 직접 읽는다. 경로 조작(`..`, 절대경로, 드라이브 문자)·제어문자·중복 이름·`incidents/*.json` 밖 파일·항목당 1 MiB 초과는 건너뛰고, 전체 압축 해제 32 MiB 초과면 중단한다.
- 건수 104, 빈·중복 본문 0, id 유일, `campaign_id` 100개, 워터마크 제거 104건을 확인하고, 하나라도 틀리면 파일을 쓰지 않는다. 기존 출력은 덮어쓰지 않는다. 로그·오류에는 본문을 넣지 않는다.
- **라벨링 파일은 그대로 평가에 쓸 수 없다** (하네스가 빈 `expected_level`을 거부한다). 사람이 `expected_level`·`split`을 채우고 검수를 마친 파일만 `evaluate.py --data`로 쓴다. 합성 데이터이므로 이 결과만으로 탐지 성능을 주장하지 않는다.

## 실행

```bash
cd backend
../.venv/Scripts/python.exe evaluate.py --data C:/ptos-eval/eval-v1.csv --output C:/ptos-eval/report-rules.md
```

| 옵션 | 설명 |
| --- | --- |
| `--data` | 평가 CSV 경로 (필수) |
| `--analyzer` | 등록된 분석기 이름. 현재 `rules`(평판 미연결로 고정한 `RuleBasedAnalyzer`)만 있다. |
| `--split` | `dev` / `test` / `all`(기본). 고른 split의 행만 분석기에 넘기고 리포트에도 그 split만 낸다. 규칙 개발 중에는 `dev`만 쓰고, `test`는 마지막 전후 비교에 한 번만 쓴다. |
| `--review-status` | 이 값의 행만 평가. 없으면 전체를 평가하고 값별 행 수만 표시한다. |
| `--timeout` | 행당 분석 제한 시간(초). 기본 5초(API 기본값과 같음). |
| `--output` | 리포트 저장 경로. 없으면 표준 출력. |

다른 분석기를 평가하려면 `backend/evaluation/harness.py`의 `ANALYZERS`에 이름과 팩토리를 등록한다. 분석기는 `Analyzer.analyze(AnalysisInput) -> AnalysisResult` 경계만 지키면 된다. 외부 전송이 있는 분석기는 별도 합의 없이 등록하지 않는다.

## 리포트 내용

- 맨 위: 코드 커밋 해시, 작업 트리 변경 여부, 평가 CSV의 SHA-256, 분석기 이름, `analysis_version`, 실행 시각, `review_status` 필터, split 필터. 같은 해시끼리만 결과를 비교한다.
- 데이터 구성: 실제·합성 행 수, `review_status`별 행 수, 합성만 있을 때 "탐지 성능 아님" 표시, campaign 누출 경고.
- `dev`, `test` 각각에 대해 **전체 / text 입력 / url 입력**으로 나눠:
  - 4단계 혼동행렬. 입력 오류(`input_error`, 예: 10,000자 초과·URL 형식 오류), 시간 초과(`timeout`), 분석 오류(`analysis_error`)는 별도 열이며 정보 부족으로 합치지 않는다.
  - 클래스별 Precision/Recall/F1. 오류 행은 해당 클래스를 맞히지 못한 것으로 재현율 분모에 포함한다. 판정 수 0이면 Precision, expected 수 0이면 Recall이 `N/A`이고, 둘 중 하나가 `N/A`이면 F1도 `N/A`다.
  - 위험 → 정상·의심 미탐 수, 위험 → 정보 부족 수(별도), 정보 부족 판정 중 expected=dangerous 비율.
- `expected=normal` 사례 표: 실제·합성별 판정 분포 한 줄씩(방어선 확인용)과 id, 입력 종류, 판정, `policy_reason`, 근거 신호 코드. 현재 분석기는 `normal`을 반환하지 않으므로 이 사례들의 실제 판정을 따로 본다.
- 불일치 id 목록 (expected와 판정이 다른 행).

리포트에는 원문, URL, `label_reason`, campaign 값을 넣지 않는다.

## 한계

- 행을 순서대로 하나씩 분석한다. 처리 시간은 측정하지 않는다 (T9).
- URL 입력은 현재 규칙 분석기에서 항상 `url_only` 정보 부족이다. 평판 조회가 미연결이기 때문이며, 이 결과를 URL 탐지 성능으로 해석하지 않는다.
- 합격선, 평가셋 규모, `review_status` 허용 값은 T1에서 정한다. 하네스에는 합격 판정이 없다.
