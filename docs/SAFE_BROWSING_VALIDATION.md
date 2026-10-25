# URL 평판 어댑터 검증 기록

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
