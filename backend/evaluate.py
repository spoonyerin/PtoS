"""Run from backend: python evaluate.py --data <저장소 밖 CSV> [--split dev|test|all] [--output <md>]. 상세는 docs/EVALUATION.md."""
import argparse
import csv
import sys
from pathlib import Path

from evaluation.harness import ANALYZERS, SPLIT_FILTERS, DatasetError, run

parser = argparse.ArgumentParser(description="고정 평가셋으로 분석기를 평가한다. 원문은 리포트에 넣지 않는다.")
parser.add_argument("--data", required=True, type=Path, help="평가 CSV 경로 (저장소·동기화 폴더 밖 권장)")
parser.add_argument("--analyzer", default="rules", choices=sorted(ANALYZERS))
parser.add_argument("--split", default="all", choices=SPLIT_FILTERS, help="이 split의 행만 평가 (기본 all). 개발 중에는 dev만 쓴다")
parser.add_argument("--review-status", help="이 review_status 값의 행만 평가")
parser.add_argument("--timeout", type=float, default=5.0, help="행당 분석 제한 시간(초)")
parser.add_argument("--output", type=Path, help="Markdown 리포트 저장 경로 (없으면 표준 출력)")
args = parser.parse_args()
# Windows 콘솔 기본 인코딩(cp949)과 무관하게 한국어 리포트·오류를 내보낸다.
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

try:
    report = run(args.data, args.analyzer, args.review_status, args.timeout, split=args.split)
except DatasetError as error:
    sys.exit(f"평가셋 형식 오류: {error}")
except (OSError, UnicodeDecodeError, csv.Error) as error:
    # 경로나 셀 값이 메시지에 섞일 수 있어 오류 종류만 알린다.
    sys.exit(f"평가 CSV를 읽지 못했어요 ({error.__class__.__name__}). UTF-8 CSV인지 확인해주세요.")

if args.output:
    args.output.write_text(report + "\n", encoding="utf-8")
else:
    print(report)
