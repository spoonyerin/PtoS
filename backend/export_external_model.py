"""Run from backend: python export_external_model.py --result <후보 결과 폴더> --out <새 모델 폴더(저장소 밖)> --version <이름> [...].

train_external.py가 남긴 후보 결과(result.json + model.joblib 또는 model/)를 서버가 읽는 모델 폴더(manifest.json)로 만든다.
임계값은 result.json의 dev 전체 임계값(final_threshold, final_normal_threshold)이다(임시, 팀 확정 필요).
"""
import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from app.model_adapter import MANIFEST_FORMAT, MANIFEST_NAME, TRANSFORMER_KIND, TRANSFORMER_WEIGHTS, file_sha256, is_inside_repo
from evaluation.harness import git_state

THRESHOLD_STATUS = "provisional-dev-crossfit"
THRESHOLD_RULE = ("학습 전용 데이터로 학습, dev 전체 점수에서 정상(legit) 행 모델 신호 0건을 지키며 사기 재현율 최대 "
                  "(dev 비교는 cross-fitted 임계값, 임시, 팀 확정 필요)")
NORMAL_RULE = "dev 사기 점수 최솟값. 그보다 낮은 점수만 정상 후보 (임시, 팀 확정 필요)"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--result", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--version", required=True)
    parser.add_argument("--train-sha256", required=True, help="학습 세트 SHA-256 (기록용)")
    parser.add_argument("--dev-sha256", required=True, help="dev CSV SHA-256 (기록용)")
    parser.add_argument("--encoder-dir", type=Path, help="고정 임베딩 후보일 때 인코더 폴더")
    parser.add_argument("--tokenizer", default="auto", choices=["auto", "kobert-sentencepiece"])
    args = parser.parse_args(argv)
    if is_inside_repo(args.out) or (args.out / MANIFEST_NAME).exists():
        print("출력 폴더는 저장소 밖의 새 폴더여야 해요.", file=sys.stderr)
        return 1
    result = json.loads((args.result / "result.json").read_text(encoding="utf-8"))
    threshold, normal = result["final_threshold"], result["final_normal_threshold"]
    args.out.mkdir(parents=True)
    commit, dirty = git_state(Path(__file__).resolve().parents[1])
    manifest = {
        "format": MANIFEST_FORMAT, "model_version": args.version,
        "threshold": threshold if threshold is not None else 1.0, "threshold_found": threshold is not None,
        "threshold_status": THRESHOLD_STATUS, "threshold_rule": THRESHOLD_RULE,
        "normal_threshold": normal if normal is not None else 0.0, "normal_threshold_found": normal is not None,
        "normal_threshold_rule": NORMAL_RULE,
        "number_masking": True,
        "text_preprocessing": "URL 구간을 '<URL>'로 치환한 뒤 전화번호·긴 숫자 가리기 (app.model_adapter.mask_numbers)",
        "label_mapping": {"positive": ["scam"], "negative": ["legit"], "source": "학습 전용 세트 label(1=사기), dev는 이진 라벨"},
        "candidate": {k: result[k] for k in ("name", "description", "config", "train_seconds", "val_auc")},
        "dev_crossfit_combined": result["combined"]["all"], "dev_model_alone": result["model_alone"],
        "train_data_sha256": args.train_sha256, "data_sha256": args.dev_sha256, "split_used": "학습 전용 세트 + dev(임계값)",
        "code_commit": commit, "worktree_dirty": dirty,
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    if (args.result / "model").is_dir():
        import torch
        import transformers
        source = args.result / "model"
        for item in source.iterdir():
            if item.is_file():
                shutil.copyfile(item, args.out / item.name)
        manifest |= {"model_file": TRANSFORMER_WEIGHTS, "model_sha256": file_sha256(args.out / TRANSFORMER_WEIGHTS),
                     "transformer": {"kind": TRANSFORMER_KIND, "tokenizer": args.tokenizer,
                                     "prefix": result["config"].get("prefix", ""), "max_length": 128,
                                     "config_sha256": file_sha256(args.out / "config.json")},
                     "libraries": {"torch": torch.__version__, "transformers": transformers.__version__},
                     "finetune": result.get("export", {})}
    else:
        import sklearn
        shutil.copyfile(args.result / "model.joblib", args.out / "model.joblib")
        manifest |= {"model_file": "model.joblib", "model_sha256": file_sha256(args.out / "model.joblib"),
                     "sklearn_version": sklearn.__version__}
        if args.encoder_dir:
            from evaluation.embedding_models import embedding_manifest
            manifest["embedding"] = embedding_manifest(result["config"]["embedding"], args.encoder_dir,
                                                       result["config"].get("prefix", ""))
    (args.out / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"모델 폴더 저장: {args.out.name} (버전 {args.version})")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
