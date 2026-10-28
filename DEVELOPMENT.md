공통 지침: [AGENTS.md](AGENTS.md)

# PtoS — 개발 작업 방식

공통 지침(제품 범위, 결정 필요 항목, 반드시 유지할 동작, 판정 계약, 구조, 주요 파일)은 `AGENTS.md`에 있다.
이 파일은 개발 작업 방식만 다룬다. 현황, 로드맵, 실행 기록은 `docs/HANDOVER.md`를 본다.
`AGENTS.md`와 이 파일이 어긋나 보이면 임의로 고르지 말고 사용자에게 알린다.

## 작업 방식

- 구현 전에 계획(바꿀 파일, 접근 방식, 테스트)을 먼저 보여주고 승인을 받는다.
- 기능별 브랜치(`feat/<주제>`)에서 작은 단위로 작업하고 커밋한다. main에 직접 커밋하지 않는다.
- 변경 후 관련 테스트를 실행하고 결과를 그대로 보고한다. 실행하지 않은 테스트를 통과했다고 쓰지 않는다.
- 탐지 성능은 고정 평가셋으로만 주장한다. 단위 테스트 통과를 정확도의 근거로 쓰지 않는다.
- `AGENTS.md`의 "결정 필요" 항목은 임의로 정하지 말고 질문한다.
- 하지 않는 일: 유료 API 호출, 사용자 입력의 외부 전송 코드 활성화, 비밀키 커밋, 원본 데이터셋 커밋, 생성물(`docs/openapi.json`, `frontend/src/api/generated.ts`) 직접 수정.

## 실행과 테스트 (Windows Git Bash)

Python 3.12 또는 3.13(3.13.15에서 확인), Node 22.12 이상, Tesseract 5 필요. 저장소 최상위 기준:

```bash
py -3 -m venv .venv
./.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
export TESSERACT_CMD='C:/Program Files/Tesseract-OCR/tesseract.exe'
./.venv/Scripts/python.exe scripts/setup_ocr.py
cd backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

- Windows에서는 `--reload`, `--workers`를 쓰지 않는다 (OCR 자식 프로세스 호환 문제). 코드 수정 후 서버를 재시작한다.
- 새 터미널에서는 `TESSERACT_CMD`를 다시 export한다. Playwright의 실제 OCR 시나리오도 이 값이 필요하다.

```bash
cd frontend && npm ci && npm run dev     # http://localhost:5173
```

테스트:

```bash
# backend/
../.venv/Scripts/python.exe -m pytest -q
RUN_REAL_OCR=1 ../.venv/Scripts/python.exe -m pytest -q tests/test_ocr_real.py
../.venv/Scripts/python.exe export_openapi.py --check
# frontend/
npm run api:check && npm test && npm run build
npx playwright install chromium && npm run test:e2e
```

계약을 바꾸면 backend에서 `export_openapi.py`, frontend에서 `npm run api:generate`를 실행하고 생성물까지 함께 커밋한 뒤 계약 검사와 테스트를 다시 돌린다.
Playwright는 Windows에서 `..\.venv\Scripts\python.exe`로 백엔드를 시작하고, 이미 떠 있는 5173/8000 서버는 재사용한다. 기본(가짜 OCR) 테스트와 실제 Tesseract 테스트를 구분해 보고한다.

## 완료 보고 형식

작업을 마치면 다음을 짧게 보고한다: 바꾼 파일, 실행한 명령과 실제 결과, 실행하지 못한 것, 남은 위험, 사람이 결정하거나 준비해야 할 것.
