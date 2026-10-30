# Codespaces에서 PtoS를 직접 조작하기

PC에 개발 도구를 설치하지 않고 GitHub 안에서 서버를 실행하는 방법입니다. **채팅 미리보기는 사용하지 않습니다.** Codespace 생성은 아래 단계에서 사용자가 직접 선택합니다. 설정 준비 과정에서 Codespace 생성, 유료 서비스 배포, PR 병합을 수행하지 않았습니다.

## 1. 자동 검사 확인

1. GitHub에 로그인하고 [저장소](https://github.com/spoonyerin/PtoS)를 엽니다. 기능 브랜치를 확인한다면 [열린 PR 목록](https://github.com/spoonyerin/PtoS/pulls)에서 해당 PR을 엽니다.
2. 확인할 커밋의 `Checks / text-analysis`가 초록색 **Success**인지 확인합니다. 대기 중이면 완료될 때까지 기다립니다.
3. PR을 확인하는 경우 **Merge pull request**는 누르지 마세요. PR 브랜치에서 바로 앱을 실행할 수 있습니다.

## 2. 브랜치를 골라 Codespace 만들기

1. [저장소 화면](https://github.com/spoonyerin/PtoS)을 엽니다. 이 링크를 여는 것만으로 Codespace가 만들어지지는 않습니다.
2. 파일 목록 위의 브랜치 선택에서 실행할 브랜치를 고릅니다. 기본은 **`main`**이고, PR을 확인한다면 그 PR의 브랜치를 검색해 선택하세요.
3. 초록색 **Code** 버튼 → **Codespaces** 탭을 누릅니다. **Local** 탭이나 **Download ZIP**은 사용하지 않습니다.
4. 생성 전 창 하단의 비용 부담 주체와 계정의 남은 무료 사용량을 확인하세요. [GitHub 청구 설정](https://github.com/settings/billing)에서 확인할 수 있으며 계정·조직별 조건이 다릅니다. 무료 사용을 보장하지 않습니다. 별도의 유료 요금제나 배포 서비스 등록은 필요하지 않습니다.
5. 직접 진행하기로 했다면 **Create codespace on <선택한 브랜치>** 또는 같은 브랜치를 대상으로 한 **＋** 생성 버튼을 누릅니다. 옵션을 고르는 경우 **… → New with options**에서 Branch가 위 브랜치인지 확인하고 기본/가장 작은 사용 가능한 머신으로 시작하세요.
6. 브라우저에서 VS Code와 비슷한 편집기가 열릴 때까지 기다립니다. Python 3.12, Node.js 24, 백엔드·프론트엔드 의존성을 자동으로 준비합니다. **설치가 끝나기 전에 앱 실행 작업을 시작하지 마세요.** 설치 완료 메시지는 `PtoS 설치 완료`입니다. 안내 파일 `docs/CODESPACES.md`도 자동으로 열립니다.

이미 이 브랜치의 Codespace가 있다면 기존 항목을 클릭해 다시 열 수 있습니다. 설정 추가 전에 만든 환경은 명령 팔레트에서 **Codespaces: Rebuild Container**가 필요할 수 있습니다. 재빌드는 기존 서버를 종료하므로 저장하지 않은 파일을 먼저 저장하세요.

## 3. 메뉴에서 두 서버 실행

1. 편집기 위쪽 **View → Command Palette…**를 누릅니다. 단축키는 Windows/Linux `Ctrl+Shift+P`, Mac `Cmd+Shift+P`입니다.
2. `Tasks: Run Task`를 입력해 해당 항목을 선택합니다.
3. 목록에서 **PtoS: 앱 실행**을 선택합니다. 작업용 파일을 신뢰할지 묻는 경우 이 저장소와 설정 내용을 확인한 뒤 허용합니다.
4. 아래 터미널에 **PtoS: 백엔드**, **PtoS: 프론트엔드** 두 작업이 열립니다. 백엔드의 `Application startup complete`, 프론트엔드의 `VITE … ready`를 확인하세요. 서버 터미널은 실행 상태로 둡니다.

앱을 이미 실행했다면 같은 작업을 중복 시작하지 마세요. Codespace를 중지했다 다시 열었을 때는 의존성 파일이 남아 있어도 서버는 다시 실행해야 합니다.

메뉴가 보이지 않을 때는 **Terminal → New Terminal**에서 다음 명령을 실행합니다. 기본 저장소 폴더에서 시작합니다.

첫 번째 터미널:

```bash
cd backend
../.venv/bin/python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --no-access-log
```

터미널 우측 **＋**로 새 터미널을 만들고 저장소 최상위에서:

```bash
cd frontend
npm run dev
```

API 키, DB, `.env` 파일은 필요하지 않습니다. Tesseract OS 패키지가 추가되었으므로 기존 Codespace는 먼저 **Codespaces: Rebuild Container**를 실행한 뒤 설치를 완료하고 다시 시작하세요. 새 Dockerfile은 Tesseract를, post-create는 검증한 kor/eng 언어 데이터를 준비합니다. 이전 예시 앱과 새 분석기의 프론트엔드/백엔드를 섞어 실행하지 마세요. 터미널이 어느 폴더인지 모르면 새 터미널에서 `pwd`로 확인하세요. Codespaces 경로는 보통 `/workspaces/PtoS`이며 이 채팅 환경의 `/workspace/PtoS`와 다릅니다. 설정은 고정 경로 대신 현재 저장소 폴더를 사용합니다.

## 4. Ports에서 실제 앱 열기

1. 아래 패널에서 **PORTS** 탭을 누릅니다. 없으면 명령 팔레트에서 **Ports: Focus on Ports View**를 검색하세요.
2. **5173 / PtoS 화면** 행을 찾습니다. 없으면 **Add Port** 또는 **Forward a Port**에 `5173`을 입력하고 Enter를 누릅니다.
3. **Port Visibility**가 **Private**인지 확인합니다. 다르면 5173 행을 우클릭 → **Port Visibility → Private**를 선택하세요. 같은 GitHub 계정으로 로그인한 브라우저에서 이용합니다. 앱 확인을 위해 Public으로 바꿀 필요가 없습니다.
4. 5173 행에 마우스를 올리고 지구본 모양의 **Open in Browser**를 누릅니다. 보이지 않으면 우클릭 메뉴의 **Open in Browser** 또는 Forwarded Address의 주소 복사를 사용하세요.
5. 새 브라우저 탭에 PtoS의 **의심스러운 문자, 함께 확인해요.** 화면이 나타납니다. 로그인이나 연결 확인 안내가 나오면 같은 GitHub 계정인지 확인하고 진행하세요.

주소는 GitHub가 생성합니다. 보통 `https://<Codespace 이름>-5173.app.github.dev` 형태입니다. 이것은 **주소 형식 예시**이며 실제 클릭 주소는 자신의 PORTS 탭에서 가져와야 합니다. `localhost:5173`, 8000 포트, 채팅의 빈 시각화 창을 열지 마세요. 컨테이너 쪽 포트 프로토콜은 HTTP를 유지하고, GitHub가 브라우저 쪽 HTTPS 연결을 제공합니다.

| 포트 | 역할 | 설정 |
| --- | --- | --- |
| 5173 | React/Vite 화면 및 `/api` 진입점 | `0.0.0.0`로 수신, Codespaces 전달, Private 유지 |
| 8000 | FastAPI | `127.0.0.1`로 수신, 자동 전달 무시, 외부 공개 불필요 |

연결 흐름: 브라우저의 GitHub HTTPS 주소 → 5173의 Vite → `/api` 요청만 내부 `http://127.0.0.1:8000`으로 전달합니다. 따라서 프론트엔드에 백엔드 외부 URL이나 비밀키를 넣거나 CORS 전체 허용을 설정할 필요가 없습니다. Vite는 GitHub가 제공하는 `CODESPACE_NAME`, `GITHUB_CODESPACES_PORT_FORWARDING_DOMAIN`으로 해당 Codespace의 정확한 5173 호스트만 허용합니다. 개발 중 화면 갱신도 같은 호스트의 WSS/443을 사용합니다.

## 5. 입력에 따른 결과 확인

1. 화면 상단의 **규칙 기반 개발 버전**과 "URL 평판 조회는 꺼져 있으며" 안내를 확인합니다(Codespace에는 평판 조회 키를 넣지 않습니다). 결과 선택 버튼은 없습니다.
2. `은행 담당자입니다. 인증번호를 알려주세요.` → **분석하기** → 임시 **위험**, 명의 주장·민감정보 요구의 실제 입력 구절을 확인합니다.
3. `앱을 설치해주세요.` → **의심**과 설치 요구 구절을 확인합니다.
4. `도서관은 내일 휴무입니다.`, `은행은 인증번호를 요구하지 않습니다.`, `그거 지금 처리`를 각각 입력합니다. 모두 **정보 부족**이지만 문장 형태·미구현 분석·단편 입력의 제한 이유가 다릅니다. 이번 버전은 규칙 부재만으로 **정상**을 반환하지 않습니다.
5. `“은행입니다. 인증번호를 알려주세요.”는 사기 예시입니다.` → 교육 인용을 실제 요구로 채택하지 않는지 확인합니다.
6. **URL 직접 입력**을 선택해 `https://예시.한국/공지`를 넣습니다. 정보 부족, 형식 확인, 평판 조회 미연결과 ASCII 호스트를 확인합니다. 주소는 클릭할 수 없습니다.
7. **문자**로 바꾸고 `(HTTPS://EXAMPLE.INVALID:443), https://example.invalid/.`를 넣어 출현 2회인 URL 1개로 표시되는지 확인합니다. `ftp://example.invalid/`를 직접 입력하면 수정 안내가 나와야 합니다.
8. **스크린샷**에서 `backend/tests/fixtures/korean-message.png` 선택 → 미리보기 → **이미지에서 글자 읽기 (OCR)**를 누릅니다. 현재 클라우드 서버로 업로드되며 별도 OCR 서비스 전송은 없습니다. 추출 문자·URL을 수정한 뒤 확인 체크와 **확인한 내용으로 분석하기**를 눌러야 결과가 나옵니다. OCR만으로 자동 분석하지 않습니다.
9. 빈 입력 안내·요청 중 중복 제출 차단도 확인하세요. 실제 개인정보는 입력하지 마세요. 이 결과는 신원·사기 확정이나 안전 보증이 아닙니다.

자세한 임시 정책은 [RULE_POLICY.md](RULE_POLICY.md), PC 실행과 확인 예시는 [README](../README.md)를 참고하세요.

## 6. 종료와 다음 실행

1. 작업을 마치면 명령 팔레트 → **Tasks: Terminate Task**에서 PtoS 작업들을 종료합니다. 직접 터미널로 실행했다면 각각 `Ctrl+C`를 누릅니다.
2. 명령 팔레트 → **Codespaces: Stop Current Codespace**로 환경을 중지합니다. 브라우저 탭을 닫는 것만으로 즉시 중지된다고 가정하지 마세요.
3. [내 Codespaces 목록](https://github.com/codespaces)에서 **… → Stop codespace**를 선택해도 됩니다. 나중에 목록에서 같은 환경을 열고 **3~4단계**를 반복합니다. 중지해도 보관 중인 저장소 용량은 계정 정책에 따라 사용량에 포함될 수 있습니다.

## 문제가 생기면

- **Codespaces 탭/생성 버튼 없음**: 로그인, 저장소 접근 권한, 조직의 Codespaces 허용 정책과 계정 사용량을 확인하세요. `github.dev` 웹 편집기는 서버를 실행하는 Codespace와 다릅니다.
- **설치 실패**: 생성 로그/터미널을 확인하고 저장소 최상위에서 `bash .devcontainer/post-create.sh`로 다시 실행합니다. 성공 후 앱 실행 작업을 선택하세요. 스크립트는 의존성을 다시 설치하며 소스·잠금 파일을 바꾸지 않습니다.
- **Blocked request / host is not allowed**: 자신의 PORTS 탭의 5173 주소인지, 실행하려던 브랜치의 최신 커밋인지 확인하세요. 환경 변수를 임의로 바꾸거나 `allowedHosts: true`로 전체 허용하지 마세요. 설정 변경 후에는 프론트엔드 작업을 종료하고 다시 실행합니다.
- **페이지 없음/연결 거부/502**: 두 서버 터미널이 실행 중인지, 5173 행이 있는지 확인하세요. 내부 백엔드 주소를 외부 브라우저 주소창에 붙여넣지 마세요.
- **API 연결 오류**: 8000 백엔드 작업의 로그를 확인하세요. 새 터미널에서 아래 세 요청이 모두 HTTP 200인지 확인합니다. 첫 두 요청은 `mode: rules`, 마지막은 `risk_level: dangerous`, `is_demo: false`여야 합니다.

```bash
curl --fail http://127.0.0.1:8000/api/v1/health/ready
curl --fail http://127.0.0.1:5173/api/v1/health/ready
curl --fail http://127.0.0.1:5173/api/v1/analyses \
  -H 'Content-Type: application/json' \
  -d '{"input_type":"text","content":"은행입니다. 인증번호를 알려주세요."}'
```

- **Address already in use / Port 5173 is already in use**: 이미 실행한 PtoS 작업을 확인해 중복 작업만 종료합니다. 포트를 임의 변경하지 마세요. 자동 전달과 호스트 설정은 5173을 기준으로 합니다.
- **다른 사람의 브라우저에서 열리지 않음**: Private 포트의 정상 동작입니다. Public으로 바꾸지 말고 본인의 로그인 계정으로 확인하세요.

## 검증의 범위와 공식 도움말

설치 스크립트, 두 작업의 실행 명령과 준비 로그 감지, Codespaces 전달 호스트 허용/차단 및 Vite → FastAPI 요청을 현재 개발 환경에서 검증했습니다. 이번 OCR 증분의 Dockerfile은 기존 Python 베이스에 OS Tesseract를 추가합니다. 현재 Linux에서는 설치·언어 데이터·실제 한국어 OCR을 검증했습니다. 전체 컨테이너 이미지 다운로드·빌드와 **실제 Codespace 생성·GitHub 로그인·외부 전달 URL 접속은 실행하지 않았습니다.** 실제 생성 성공 여부는 계정 권한·사용량·GitHub 서비스 상태에도 영향을 받습니다. PR Checks의 통과와 실제 Codespace 생성 검증을 구분하세요.

- [GitHub: 저장소에서 Codespace 만들기](https://docs.github.com/en/codespaces/developing-in-a-codespace/creating-a-codespace-for-a-repository)
- [GitHub: Codespaces 포트 전달](https://docs.github.com/en/codespaces/developing-in-a-codespace/forwarding-ports-in-your-codespace)
- [GitHub: 기본 환경 변수](https://docs.github.com/en/codespaces/developing-in-a-codespace/default-environment-variables-for-your-codespace)
