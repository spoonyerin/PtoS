#!/usr/bin/env bash
set -euo pipefail

ptos_root="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ptos_root"

python3 --version
node --version
python3 -m venv .venv
.venv/bin/python -m pip install -r backend/requirements-dev.txt
.venv/bin/python -m pip check
.venv/bin/python scripts/setup_ocr.py
npm --prefix frontend ci

printf '\nPtoS 설치 완료. 명령 팔레트 → Tasks: Run Task → PtoS: 앱 실행 을 선택하세요.\n'
