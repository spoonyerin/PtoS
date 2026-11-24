"""Run from backend: python train_external.py --train <finetune-train.csv> --val <finetune-val.csv> --data <dev CSV> --out-dir <저장소 밖>.

학습 전용 데이터로 후보를 학습하고 dev(cross-fitted 임계값)로 비교한다. 상세는 evaluation/external_training.py.
후보: tfidf, embed:<이름>=<폴더>[|<입력 앞 글자>] (고정 임베딩 + 로지스틱 회귀).
"""
import argparse
import sys
from pathlib import Path

from app.model_adapter import is_inside_repo
from evaluation.external_training import Candidate, compare_external
from evaluation.model_training import DEFAULT_CONFIG, build_pipeline


def _joblib_export(target: Path, model) -> dict:
    import joblib
    from app.model_adapter import file_sha256
    path = target / "model.joblib"
    joblib.dump(model.export() if hasattr(model, "export") else model, path)
    return {"model_file": path.name, "model_sha256": file_sha256(path)}


def _candidates(specs: list[str]) -> list[Candidate]:
    out = []
    for spec in specs:
        if spec == "tfidf":
            out.append(Candidate("tfidf-lr", "TF-IDF 문자 2-4gram + 로지스틱 회귀 (기존 기준선 설정)",
                                 lambda seed: build_pipeline(DEFAULT_CONFIG, seed), _joblib_export, DEFAULT_CONFIG))
        elif spec.startswith("embed:"):
            from evaluation.embedding_models import EmbeddingClassifier, cached, local_transformer_encoder
            name, _, rest = spec[len("embed:"):].partition("=")
            folder, _, prefix = rest.partition("|")
            encode = cached(local_transformer_encoder(Path(folder), prefix))
            out.append(Candidate(f"{name}-frozen-lr", f"고정 임베딩({name}, 입력 앞 '{prefix}') + 로지스틱 회귀",
                                 lambda seed, encode=encode: EmbeddingClassifier(encode, seed), _joblib_export,
                                 {"embedding": name, "folder": Path(folder).name, "prefix": prefix}))
        elif spec.startswith("ft:"):
            # ft:<이름>=<폴더>|<입력 앞 글자>|<학습률>
            from evaluation.finetune_models import FineTunedClassifier, KoBertTokenizer
            name, _, rest = spec[len("ft:"):].partition("=")
            folder, prefix, lr = (rest.split("|") + ["", ""])[:3]
            lr = float(lr) if lr else 5e-5
            tok = KoBertTokenizer if name.startswith("kobert") else None
            out.append(Candidate(
                f"{name}-finetune", f"미세조정({name}, 입력 앞 '{prefix}', 학습률 {lr:g}, 최대 128토큰, 2 epoch)",
                lambda seed, folder=folder, prefix=prefix, lr=lr, tok=tok: FineTunedClassifier(
                    Path(folder), seed, prefix=prefix, lr=lr, tokenizer_factory=tok, log=lambda m: print(m, flush=True)),
                lambda target, model: model.save(target / "model"),
                {"base": name, "folder": Path(folder).name, "prefix": prefix, "lr": lr}))
        else:
            raise SystemExit(f"알 수 없는 후보: {spec}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", required=True, type=Path)
    parser.add_argument("--val", type=Path)
    parser.add_argument("--data", required=True, type=Path, help="dev만 든 평가 CSV")
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--candidate", action="append", required=True)
    parser.add_argument("--seed", type=int, default=20261124)
    parser.add_argument("--n-splits", type=int, default=5)
    args = parser.parse_args(argv)
    if is_inside_repo(args.out_dir) or is_inside_repo(args.report):
        print("출력은 저장소 밖에 두세요.", file=sys.stderr)
        return 1
    report = compare_external(args.train, args.val, args.data, args.out_dir, _candidates(args.candidate),
                              args.seed, args.n_splits)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(report + "\n", encoding="utf-8")
    print(f"리포트 저장: {args.report.name}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
