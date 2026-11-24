"""Run from backend: python compare_models.py --data <저장소 밖 CSV> --output <저장소 밖 리포트>. 상세는 docs/EVALUATION.md.

split=dev 행만 써서 경량 모델 후보의 교차검증 집계를 비교한다. 모델 파일을 만들지 않고 test 행은 쓰지 않는다.
"""
import argparse
import csv
import sys
from pathlib import Path

from app.model_adapter import is_inside_repo
from evaluation.harness import DatasetError
from app.embedding_encoder import EncoderUnavailable
from evaluation.embedding_models import cached, embedding_candidate, local_transformer_encoder
from evaluation.model_comparison import CANDIDATES, compare, render_comparison_report
from evaluation.model_training import LABEL_SOURCES, TrainingError


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="dev split 교차검증으로 경량 모델 후보를 비교한다. 리포트에는 집계만 넣는다.")
    parser.add_argument("--data", required=True, type=Path, help="평가 CSV 경로 (저장소·동기화 폴더 밖 권장)")
    parser.add_argument("--seed", type=int, default=20261027)
    parser.add_argument("--n-splits", type=int, default=5, help="campaign_id 기준 교차검증 fold 수")
    parser.add_argument("--labels", choices=LABEL_SOURCES, default="levels", help="라벨 기준 (train_model.py와 같음)")
    parser.add_argument("--exclude-source", action="append", default=[], metavar="글자",
                        help="source 열에 이 글자가 든 dev 행은 학습에서 빼고 채점만 한다 (여러 번 지정 가능)")
    parser.add_argument("--candidates", nargs="+", choices=list(CANDIDATES), help="비교할 기본 후보. 없으면 전체")
    parser.add_argument("--embedding", action="append", default=[], metavar="이름=폴더",
                        help="미리 내려받은 인코더 모델 폴더를 고정 임베딩 후보로 더한다 (torch·transformers 필요, 여러 번 지정 가능)")
    parser.add_argument("--embedding-prefix", default="", help="임베딩 입력 앞에 붙일 글자 (모델이 요구할 때만)")
    parser.add_argument("--output", type=Path, help="리포트 저장 경로 (저장소 밖). 없으면 표준 출력")
    args = parser.parse_args(argv)

    if args.output and is_inside_repo(args.output):
        print("리포트는 저장소 밖에 저장해주세요.", file=sys.stderr)
        return 1
    extra = {}
    for item in args.embedding:
        name, _, folder = item.partition("=")
        if not name.strip() or not folder.strip() or name in CANDIDATES or name in extra:
            print("--embedding은 '이름=폴더' 형식이고 이름이 겹치지 않아야 해요.", file=sys.stderr)
            return 1
        try:
            extra[name.strip()] = embedding_candidate(name.strip(), cached(local_transformer_encoder(Path(folder.strip()), args.embedding_prefix)))
        except EncoderUnavailable as error:
            print(f"임베딩 후보 준비 오류: {error}", file=sys.stderr)
            return 1
    names = [*(args.candidates or CANDIDATES), *extra] if extra else args.candidates
    try:
        report = render_comparison_report(compare(args.data, args.seed, args.n_splits, args.labels, names,
                                                  exclude_sources=args.exclude_source, extra_candidates=extra))
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
