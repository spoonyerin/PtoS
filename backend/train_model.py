"""Run from backend: python train_model.py --data <저장소 밖 CSV> --out-dir <저장소 밖 새 폴더>. 상세는 docs/EVALUATION.md.

split=dev 행만 학습하고 test 행은 쓰지 않는다. 출력: model.joblib, manifest.json, train-report.md (원문 없음).
"""
import argparse
import csv
import sys
from pathlib import Path

from evaluation.harness import DatasetError
from evaluation.model_training import TrainingError, train

parser = argparse.ArgumentParser(description="dev split으로 TF-IDF + 로지스틱 회귀 기준선을 학습한다. 원문은 리포트에 넣지 않는다.")
parser.add_argument("--data", required=True, type=Path, help="평가 CSV 경로 (저장소·동기화 폴더 밖 권장)")
parser.add_argument("--out-dir", required=True, type=Path, help="모델을 저장할 새 폴더 (저장소 밖)")
parser.add_argument("--seed", type=int, default=20261027)
parser.add_argument("--n-splits", type=int, default=5, help="campaign_id 기준 교차검증 fold 수")
parser.add_argument("--model-version", default="tfidf-lr-v1")
args = parser.parse_args()
sys.stdout.reconfigure(encoding="utf-8")
sys.stderr.reconfigure(encoding="utf-8")

try:
    manifest = train(args.data, args.out_dir, args.seed, args.n_splits, args.model_version)
except (DatasetError, TrainingError) as error:
    sys.exit(f"학습 입력 오류: {error}")
except (OSError, UnicodeDecodeError, csv.Error) as error:
    sys.exit(f"평가 CSV를 읽지 못했어요 ({error.__class__.__name__}). UTF-8 CSV인지 확인해주세요.")

counts = manifest["counts"]
threshold = f"{manifest['threshold']:.3f}" if manifest["threshold_found"] else "찾지 못함"
print(f"모델 {manifest['model_version']} 저장 완료: dev {counts['train_rows']}건 학습, test {counts['test_rows_dropped']}건 미사용")
print(f"임시 임계값({manifest['threshold_status']}): {threshold}, OOF 모델 신호 {manifest['oof_model_counts']}")
print("자세한 집계는 출력 폴더의 train-report.md를 보세요.")
