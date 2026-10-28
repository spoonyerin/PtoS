# Windows Git Bash에서 OCR 앱 확인하기

이 문서는 Windows용 Git Bash 기준이다. PowerShell의 역슬래시 명령과 섞지 않는다. Windows에서는 OS용 실행 파일과 Python의 subprocess 지원 이벤트 루프가 필요하다.

## 1. main 브랜치 받기

기존 두 서버를 각각 `Ctrl+C`로 종료한다. PtoS 폴더에서 Git Bash를 열고:

```bash
git fetch origin
git switch main
git pull --ff-only
```

필요한 도구는 Git, Python 3.12 또는 3.13, Node.js 22.12 이상(검증은 24), Tesseract 5다. Python/Node가 이미 설치되어 있다면 유지한다. `py -0`, `node --version`으로 확인한다. 2026-10-26에 Windows 11 / Python 3.13.15 / Tesseract v5.5.3에서 백엔드, 실제 OCR, Playwright를 실행했다 (`docs/HANDOVER.md` 9절).

URL 평판 조회(Google Safe Browsing)는 **기본 꺼짐**이다. 실행·OCR 설치는 기존과 같고 키 없이도 앱은 동작한다. 키와 `PTOS_SAFE_BROWSING_MODE=live-noncommercial`을 백엔드 셸에 둘 다 넣었을 때만 외부 조회가 켜진다. 켜는 방법과 수동 확인은 [SAFE_BROWSING.md](SAFE_BROWSING.md)를 참고한다.

## 2. 무료 Tesseract 설치

1. [Tesseract 공식 설치 안내](https://tesseract-ocr.github.io/tessdoc/Installation.html)의 Windows 항목에서 [UB Mannheim Windows 배포 안내](https://github.com/UB-Mannheim/tesseract/wiki)로 이동한다.
2. 자신의 Windows에 맞는 Tesseract **5.x** 설치 프로그램을 내려받고 설치한다. 설치 경로를 기록한다. 계정 가입·결제·API 키는 필요 없다. 설치 프로그램을 구하기 위해 임의의 블로그 실행 파일을 받지 않는다.
3. 보통 설치 경로는 `C:\Program Files\Tesseract-OCR\tesseract.exe`다. 다른 경로라면 다음 명령의 경로를 바꾼다.

저장소 최상위의 Git Bash에서:

```bash
export TESSERACT_CMD='C:/Program Files/Tesseract-OCR/tesseract.exe'
"$TESSERACT_CMD" --version
py -3 -m venv .venv
./.venv/Scripts/python.exe -m pip install -r backend/requirements-dev.txt
./.venv/Scripts/python.exe scripts/setup_ocr.py
```

`tesseract 5...`와 `한국어 OCR 준비 완료`를 확인한다. `setup_ocr.py`는 공식 tessdata_fast 4.1.0의 kor/eng 데이터를 `.ocr/tessdata/`에 내려받고 고정 SHA-256을 검사한다. 이 폴더는 Git에서 제외된다. 인터넷은 최초 설치 때 필요하며 **OCR 실행 중에는 이미지/텍스트를 외부 OCR 서비스로 보내거나 언어 데이터를 자동 다운로드하지 않는다.** 해시/TLS 오류를 무시하지 말고 네트워크·인증서 설정을 확인한다.

Windows 배포판의 `tesseract v5.5.3.20260724`처럼 버전 앞에 `v`가 있는 출력도 허용한다. 준비 스크립트는 `tesseract 5.`/`tesseract v5.` 두 형식을 지원한다. 런타임 OCR 어댑터에는 이 문자열 접두사 버전 검사가 없으며 CLI 실행과 kor/eng 언어 로딩 실패를 검사한다.

`TESSERACT_CMD`는 현재 Git Bash와 그 안에서 실행한 백엔드에 적용된다. 새 터미널을 열거나 PC를 재시작했다면 다시 export한다. 경로에 공백이 있으므로 따옴표를 유지한다. `.env` 자동 로딩은 사용하지 않는다. 이미 별도 `TESSDATA_PREFIX`를 지정했다면 프로젝트의 언어 데이터 대신 그 경로를 사용하므로 kor/eng가 모두 있는지 확인한다.

## 3. 두 서버 실행

같은 첫 번째 Git Bash 터미널에서:

```bash
cd backend
../.venv/Scripts/python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log
```

**Windows에서는 `--reload`와 `--workers`를 추가하지 않는다.** 현재 Uvicorn의 Windows reload 모드는 subprocess를 지원하지 않는 Selector 루프를 선택한다. 단일 서버 명령은 Proactor 루프를 사용하여 Tesseract 파이프를 실행한다. 코드를 수정했다면 `Ctrl+C` 후 같은 명령으로 다시 실행한다. Linux/Codespaces의 reload는 이 Windows 제한과 다르다.

두 번째 Git Bash 터미널을 PtoS 최상위에서 열고:

```bash
cd frontend
npm ci
npm run dev
```

첫 터미널에 `Application startup complete`, 두 번째 터미널에 Vite `ready`가 보이면 둘 다 실행해둔다. PC 브라우저 주소창에 **http://localhost:5173**을 입력한다. 이미지의 처리 장소는 이 PC의 FastAPI다. 반면 Codespaces에서 실행하면 해당 클라우드 서버로 업로드된다.

## 4. 직접 확인할 순서

1. **문자**, **URL 직접 입력**으로 이전 기능이 유지되는지 확인한다.
2. **스크린샷**을 선택하고 파일 선택 버튼으로 `backend/tests/fixtures/korean-message.png`를 연다. 합성한 연습용 한국어 이미지다. 미리보기만 나타나고 위험 결과는 나오지 않아야 한다.
3. **이미지에서 글자 읽기 (OCR)**를 누른다. 추출 내용, URL 후보와 경고가 나타나고 **확인한 내용으로 분석하기**는 비활성 상태여야 한다. 주소는 클릭되지 않으며 평판 조회는 하지 않는다.
4. 원본과 추출 문장을 비교한다. 텍스트 영역에서 글자와 URL을 직접 수정할 수 있다. 예를 들어 아래 한 줄을 직접 확인·입력한다. URL의 O/0·l/1, 잘린 주소를 시스템이 추측해 바꾸지 않는다.

   ```text
   은행입니다. 인증번호를 알려주세요. https://example.invalid/corrected
   ```

5. URL 후보가 `/corrected`로 갱신된 것을 확인한다. **추출한 문자와 URL을 원본과 비교해 확인했습니다.**를 체크하고 **확인한 내용으로 분석하기**를 누른다. 기존 규칙의 임시 **위험** 경고와 URL **평판 조회 미연결**이 나와야 한다. 이는 실제 사칭/악성 검증이 아니다.
6. 다시 텍스트를 수정하면 이전 위험 결과와 확인 체크가 해제되는지 확인한다. 다른 이미지 선택, **이미지 지우기 / 취소**, 문자 입력 방식 변경도 이전 OCR 확인을 해제한다. 같은 이미지를 다시 읽으려면 OCR 버튼을 다시 누르거나 이미지 지우기 후 재선택한다.
7. 빈 흰 JPG/PNG에서는 **문자를 찾지 못했어요**와 재업로드/직접 입력 안내가 나와야 한다. 실제 형식이 다른 위장 파일, 손상 파일, 제한 초과는 분석하지 않는다. 인식이 불명확하면 확인 체크를 하지 말고 선명한 이미지로 재업로드하거나 문자로 직접 입력한다.

처리 제한은 **10 MiB·2,000만 화소**, 엔진 실행 **15초**, 브라우저 OCR 대기 **25초**다. 모두 개발 제안이며 PRD 확정값/응답 보장이 아니다. 시간 초과·서버 실패는 정상/정보 부족 판정으로 바꾸지 않는다. 이미지·추출 원문은 분석 이력, 로그, 서버 임시파일에 저장하지 않는다. 현재 확인 화면에는 메모리로 남는다.

## 5. 문제가 생기면

- `py` 없음: Python 3.12와 Python Launcher 설치를 확인하고 새 Git Bash를 연다. `python --version`이 3.12라면 venv 생성에 `python -m venv .venv`도 사용할 수 있다.
- Tesseract 경로 오류: `"$TESSERACT_CMD" --version`부터 확인한다. 경로·따옴표를 고치고 같은 터미널에서 백엔드를 재시작한다.
- 한국어 OCR 미준비: 저장소 최상위에서 `./.venv/Scripts/python.exe scripts/setup_ocr.py`를 다시 실행한다. kor만 빠져도 영어 OCR로 몰래 대체하지 않는다.
- OCR 실패/NotImplementedError: Windows 백엔드에 `--reload`/여러 workers를 사용하지 않았는지 확인한다. 개인정보가 담긴 원문·OCR stderr를 공유하지 않고 설치 상태/오류 코드만 확인한다.
- API 연결 오류: 두 서버와 포트 5173/8000을 확인한다. 백엔드가 다른 브랜치나 이전 코드로 떠 있으면 종료 후 현재 브랜치에서 재시작한다.
- 프로그램 종료: 두 터미널에서 각각 `Ctrl+C`. 브라우저를 새로고침하면 입력·추출 결과는 복구되지 않는다.

정책과 교체 지점은 [OCR_POLICY.md](OCR_POLICY.md), Linux·Codespaces 및 전체 테스트 명령은 [README](../README.md)를 참고한다.
