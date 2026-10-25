"""Run from backend: python export_openapi.py (or --check)."""
import json
import sys
from pathlib import Path

from app.main import app

path = Path(__file__).resolve().parents[1] / "docs" / "openapi.json"
content = json.dumps(app.openapi(), ensure_ascii=False, indent=2) + "\n"
if "--check" in sys.argv:
    if not path.exists() or path.read_text() != content:
        sys.exit("API 계약이 변경되었습니다. python export_openapi.py 후 frontend에서 npm run api:generate를 실행하세요.")
else:
    path.write_text(content)
