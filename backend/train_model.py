"""Run from backend: python train_model.py --data <저장소 밖 CSV> --out-dir <저장소 밖 새 폴더>. 상세는 docs/EVALUATION.md.

split=dev 행만 학습하고 test 행은 쓰지 않는다. 출력: model.joblib, manifest.json, train-report.md (원문 없음).
"""
import argparse
import csv
import sys
from pathlib import Path

from app.model_adapter import is_inside_repo
from evaluation.harness import DatasetError
from app.embedding_encoder import EncoderUnavailable
from evaluation.embedding_models import cached, embedding_candidate, embedding_manifest, local_transformer_encoder
from evaluation.model_comparison import BASELINE, CANDIDATES, build_candidate
from evaluation.model_training import LABEL_SOURCES, TrainingError, train

parser = argparse.ArgumentParser(description="dev split으로 TF-IDF + 로지스틱 회귀 기준선을 학습한다. 원문은 리포트에 넣지 않는다.")
parser.add_argument("--data", required=True, type=Path, help="평가 CSV 경로 (저장소·동기화 폴더 밖 권장)")
parser.add_argument("--out-dir", required=True, type=Path, help="모델을 저장할 새 폴더 (저장소 밖)")
parser.add_argument("--seed", type=int, default=20261027)
parser.add_argument("--n-splits", type=int, default=5, help="campaign_id 기준 교차검증 fold 수")
parser.add_argument("--model-version", default="tfidf-lr-v1")
parser.add_argument("--labels", choices=LABEL_SOURCES, default="levels",
                    help="학습 라벨 기준. levels(기본): 4단계 라벨. binary: expected_binary 우선, 없으면 4단계에서 파생 (임시, 팀 확정 필요)")
parser.add_argument("--exclude-source", action="append", default=[], metavar="글자",
                    help="source 열에 이 글자가 든 dev 행은 학습에서 빼고 채점만 한다 (여러 번 지정 가능)")
parser.add_argument("--candidate", choices=list(CANDIDATES), default=BASELINE,
                    help="학습할 모델 구성 (compare_models.py의 후보 이름). 기본은 현재 기준선")
parser.add_argument("--embedding", metavar="이름=폴더",
                    help="미리 내려받은 인코더 폴더(저장소 밖)의 고정 임베딩 + 로지스틱 회귀를 학습한다. --candidate 대신 쓴다 (torch·transformers 필요)")
parser.add_argument("--embedding-prefix", default="", help="임베딩 입력 앞에 붙일 글자 (모델이 요구할 때만)")
args = parser.parse_args()
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

config, factory, embedding = CANDIDATES[args.candidate]["config"], build_candidate, None
if args.embedding:
    name, _, folder = (part.strip() for part in args.embedding.partition("="))
    if not name or not folder:
        sys.exit("--embedding은 '이름=폴더' 형식이어야 해요.")
    if is_inside_repo(Path(folder)):
        sys.exit("임베딩 모델 폴더는 저장소 밖이어야 해요.")
    try:
        candidate = embedding_candidate(name, cached(local_transformer_encoder(Path(folder), args.embedding_prefix)))
        embedding = embedding_manifest(name, Path(folder), args.embedding_prefix)
    except EncoderUnavailable as error:
        sys.exit(f"임베딩 모델 준비 오류: {error}")
    config, factory = candidate["config"], candidate["factory"]

try:
    manifest = train(args.data, args.out_dir, args.seed, args.n_splits, args.model_version, label_source=args.labels,
                     config=config, pipeline_factory=factory, exclude_sources=args.exclude_source, embedding=embedding)
except (DatasetError, TrainingError) as error:
    sys.exit(f"학습 입력 오류: {error}")
except (OSError, UnicodeDecodeError, csv.Error) as error:
    sys.exit(f"평가 CSV를 읽지 못했어요 ({error.__class__.__name__}). UTF-8 CSV인지 확인해주세요.")

counts = manifest["counts"]
threshold = f"{manifest['threshold']:.3f}" if manifest["threshold_found"] else "찾지 못함"
print(f"모델 {manifest['model_version']} 저장 완료: dev {counts['train_rows']}건 학습, test {counts['test_rows_dropped']}건 미사용")
print(f"임시 임계값({manifest['threshold_status']}): {threshold}, OOF 모델 신호 {manifest['oof_model_counts']}")
print("자세한 집계는 출력 폴더의 train-report.md를 보세요.")
