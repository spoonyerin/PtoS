"""Run from backend: python compare_models.py --data <저장소 밖 CSV> --output <저장소 밖 리포트>. 상세는 docs/EVALUATION.md.

split=dev 행만 써서 경량 모델 후보의 교차검증 집계를 비교한다. 모델 파일을 만들지 않고 test 행은 쓰지 않는다.
"""
import argparse
import csv
import sys
from pathlib import Path

from app.model_adapter import is_inside_repo
from evaluation.harness import DatasetError
from evaluation.model_comparison import CANDIDATES, compare, render_comparison_report
from evaluation.model_training import LABEL_SOURCES, TrainingError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="dev split 교차검증으로 경량 모델 후보를 비교한다. 리포트에는 집계만 넣는다.")
    parser.add_argument("--data", required=True, type=Path, help="평가 CSV 경로 (저장소·동기화 폴더 밖 권장)")
    parser.add_argument("--seed", type=int, default=20261027)
    parser.add_argument("--n-splits", type=int, default=5, help="campaign_id 기준 교차검증 fold 수")
    parser.add_argument("--labels", choices=LABEL_SOURCES, default="levels", help="라벨 기준 (train_model.py와 같음)")
    parser.add_argument("--candidates", nargs="+", choices=list(CANDIDATES), help="비교할 후보. 없으면 전체")
    parser.add_argument("--output", type=Path, help="리포트 저장 경로 (저장소 밖). 없으면 표준 출력")
    args = parser.parse_args(argv)

    if args.output and is_inside_repo(args.output):
        print("리포트는 저장소 밖에 저장해주세요.", file=sys.stderr)
        return 1
    try:
        report = render_comparison_report(compare(args.data, args.seed, args.n_splits, args.labels, args.candidates))
    except (DatasetError, TrainingError) as error:
        print(f"비교 입력 오류: {error}", file=sys.stderr)
        return 1
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        print(f"평가 CSV를 읽지 못했어요 ({error.__class__.__name__}). UTF-8 CSV인지 확인해주세요.", file=sys.stderr)
        return 1
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report + "\n", encoding="utf-8")
        print(f"리포트 저장: {args.output.name}")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
