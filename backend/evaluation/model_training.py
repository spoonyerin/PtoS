"""TF-IDF 문자 n-gram + 로지스틱 회귀 기준선 학습 (T5, 개발용).

- split=dev 행만 학습·임계값 결정에 쓴다. test 행은 읽은 직후 버리고 건수만 기록한다.
- dev 안에서 campaign_id 기준 층화 그룹 교차검증으로 out-of-fold(OOF) 점수를 내고, 임계값은 OOF 점수로만 정한다.
- 임계값 기준(임시, 팀 확정 필요): expected=normal 행이 모델 신호로 표시되는 경우 0건을 지키면서 사기 재현율 최대.
- 모델 파일·manifest·리포트는 저장소 밖에만 쓴다. 리포트에는 id와 집계만 넣고 원문을 넣지 않는다.
"""

import asyncio
import json
import platform
import tempfile
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.analyzers import CompositeAnalyzer, RuleBasedAnalyzer
from app.contracts import RiskLevel
from app.model_adapter import MANIFEST_FORMAT, MANIFEST_NAME, ModelState, file_sha256, is_inside_repo, prepare_model_text
from app.url_reputation import DisconnectedReputationProvider
from app.urls import UrlInputError, extract_urls

from .harness import DatasetError, EvalRow, Outcome, _analyze_one, _metrics_section, _table, git_state, load_rows

MODEL_FILE = "model.joblib"
REPORT_FILE = "train-report.md"
THRESHOLD_STATUS = "provisional-dev-cv"
THRESHOLD_RULE = "OOF 점수에서 expected=normal 행 모델 신호 0건을 지키며 사기 재현율 최대 (임시, 팀 확정 필요)"
POSITIVE_LEVELS = (RiskLevel.SUSPICIOUS.value, RiskLevel.DANGEROUS.value)
NEGATIVE_LEVELS = (RiskLevel.NORMAL.value,)
# 개발 기본 설정. 성능 근거로 고른 값이 아니다.
DEFAULT_CONFIG = {
    "vectorizer": {"analyzer": "char_wb", "ngram_range": [2, 4], "min_df": 1, "sublinear_tf": True},
    "classifier": {"C": 1.0, "class_weight": "balanced", "solver": "liblinear", "max_iter": 1000},
}


class TrainingError(ValueError):
    """학습 입력 오류. 메시지에 원문·셀 값을 넣지 않는다."""


def build_pipeline(config: dict, seed: int):
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import Pipeline

    vectorizer = dict(config["vectorizer"], ngram_range=tuple(config["vectorizer"]["ngram_range"]))
    return Pipeline([
        ("tfidf", TfidfVectorizer(**vectorizer)),
        ("clf", LogisticRegression(**config["classifier"], random_state=seed)),
    ])


@dataclass
class TrainingSet:
    rows: list[EvalRow]
    texts: list[str] = field(repr=False)
    labels: list[int]
    groups: list[str]
    test_rows_dropped: int = 0
    excluded: dict[str, int] = field(default_factory=dict)


def select_training_rows(rows: list[EvalRow]) -> TrainingSet:
    dev = [row for row in rows if row.split == "dev"]
    excluded = {"url_input": 0, "insufficient_label": 0, "url_extraction_error": 0, "empty_campaign_id": 0}
    selected, texts, labels, groups = [], [], [], []
    for row in dev:
        if row.input_type != "text":
            excluded["url_input"] += 1
            continue
        if row.expected in POSITIVE_LEVELS:
            label = 1
        elif row.expected in NEGATIVE_LEVELS:
            label = 0
        else:
            excluded["insufficient_label"] += 1
            continue
        try:
            spans = extract_urls(row.content).spans
        except UrlInputError:
            excluded["url_extraction_error"] += 1
            continue
        if not row.campaign_id:
            # 묶음 정보가 없으면 행 하나를 하나의 묶음으로 본다.
            excluded["empty_campaign_id"] += 1
        selected.append(row)
        texts.append(prepare_model_text(row.content, spans))
        labels.append(label)
        groups.append(row.campaign_id or f"row:{row.id}")
    return TrainingSet(selected, texts, labels, groups, len(rows) - len(dev), excluded)


def cross_validate(data: TrainingSet, config: dict, seed: int, n_splits: int,
                   pipeline_factory: Callable[[dict, int], object] = build_pipeline) -> tuple[list[float], list[int]]:
    """OOF 점수와 각 행의 fold 번호. 같은 campaign은 한 fold에만 들어간다."""
    from sklearn.model_selection import StratifiedGroupKFold

    for label, name in ((1, "사기"), (0, "정상")):
        if len({g for g, y in zip(data.groups, data.labels) if y == label}) < n_splits:
            raise TrainingError(f"{name} 라벨의 campaign 수가 fold 수({n_splits})보다 적어요.")
    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    scores: list[float | None] = [None] * len(data.texts)
    folds = [-1] * len(data.texts)
    for fold, (train_idx, val_idx) in enumerate(splitter.split(data.texts, data.labels, data.groups)):
        train_labels = {data.labels[i] for i in train_idx}
        if train_labels != {0, 1}:
            raise TrainingError(f"fold {fold}의 학습 부분에 한 라벨만 있어요.")
        pipeline = pipeline_factory(config, seed)
        pipeline.fit([data.texts[i] for i in train_idx], [data.labels[i] for i in train_idx])
        positive = list(pipeline.classes_).index(1)
        for i, proba in zip(val_idx, pipeline.predict_proba([data.texts[i] for i in val_idx])):
            scores[i] = float(proba[positive])
            folds[i] = fold
    return [float(s) for s in scores], folds


def choose_threshold(scores: list[float], labels: list[int]) -> float | None:
    """normal 점수 최댓값보다 큰 사기 점수 중 가장 낮은 값. 없으면 None(신호를 낼 임계값 없음)."""
    max_normal = max((s for s, y in zip(scores, labels) if y == 0), default=float("-inf"))
    above = [s for s, y in zip(scores, labels) if y == 1 and s > max_normal]
    return min(above) if above else None


def model_counts(scores: list[float], labels: list[int], threshold: float | None) -> dict[str, int]:
    flagged = [threshold is not None and s >= threshold for s in scores]
    return {
        "tp": sum(f and y == 1 for f, y in zip(flagged, labels)),
        "fn": sum(not f and y == 1 for f, y in zip(flagged, labels)),
        "fp": sum(f and y == 0 for f, y in zip(flagged, labels)),
        "tn": sum(not f and y == 0 for f, y in zip(flagged, labels)),
    }


class _FixedScoreModel:
    """OOF 종합 평가용: 해당 행의 fold 밖 모델 점수를 그대로 낸다."""

    def __init__(self, score: float, threshold: float, version: str):
        self._score, self.threshold, self.version = score, threshold, version

    def score(self, text: str) -> float:
        return self._score


async def oof_outcomes(data: TrainingSet, scores: list[float], threshold: float | None,
                       version: str, timeout: float) -> tuple[list[Outcome], list[Outcome]]:
    rules = RuleBasedAnalyzer(DisconnectedReputationProvider("training_offline"))
    rules_only, combined = [], []
    for row, score in zip(data.rows, scores):
        rules_only.append(await _analyze_one(rules, row, timeout))
        # 임계값이 없으면 1보다 큰 값을 넣어 모델 신호가 나오지 않게 한다.
        model = _FixedScoreModel(score, threshold if threshold is not None else 2.0, version)
        combined.append(await _analyze_one(CompositeAnalyzer(rules, ModelState("loaded", model)), row, timeout))
    return rules_only, combined


def _library_versions() -> dict[str, str]:
    import joblib
    import numpy
    import scipy
    import sklearn
    return {"python": platform.python_version(), "scikit-learn": sklearn.__version__, "numpy": numpy.__version__,
            "scipy": scipy.__version__, "joblib": joblib.__version__}


def _fmt(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def render_training_report(manifest: dict, data: TrainingSet, counts: dict[str, int],
                           folds: list[int], rules_only: list[Outcome], combined: list[Outcome]) -> str:
    recall = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else None
    precision = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else None
    raised = [c for r, c in zip(rules_only, combined) if r.predicted != c.predicted]
    lines = [
        "# PtoS 모델 학습 리포트 (dev 교차검증)", "",
        *_table(["항목", "값"], [
            ["모델 버전", manifest["model_version"]],
            ["코드 커밋", f"`{manifest['code_commit']}`"],
            ["작업 트리", {True: "변경 있음", False: "변경 없음", None: "확인 불가"}[manifest["worktree_dirty"]]],
            ["평가 CSV SHA-256", f"`{manifest['data_sha256']}`"],
            ["모델 파일 SHA-256", f"`{manifest['model_sha256']}`"],
            ["시드 / fold 수", f"{manifest['seed']} / {manifest['n_splits']}"],
            ["임계값", _fmt(manifest["threshold"]) if manifest["threshold_found"] else "찾지 못함 (모델 신호 꺼짐)"],
            ["임계값 상태", f"{manifest['threshold_status']} — {manifest['threshold_rule']}"],
            ["라이브러리", ", ".join(f"{k} {v}" for k, v in manifest["libraries"].items())],
            ["실행 시각", manifest["created_at"]],
        ]), "",
        "리포트에는 원문·URL·라벨 근거·campaign 값을 넣지 않는다. 행은 id로만 표시한다.",
        "**소규모 dev 교차검증이며 탐지 성능 수치가 아니다. 임계값과 정책은 임시다.**", "",
        "## 데이터", "",
        f"- 학습에 쓴 dev 행: {len(data.rows)}건 (사기 {sum(data.labels)}, 정상 {len(data.labels) - sum(data.labels)}), campaign {len(set(data.groups))}개",
        f"- test 행: {data.test_rows_dropped}건은 읽은 직후 버렸고 학습·임계값에 쓰지 않았다.",
        "- 제외: " + ", ".join(f"{k} {v}" for k, v in data.excluded.items()),
        f"- 합성 {sum(r.is_synthetic for r in data.rows)}건, 실제 {sum(not r.is_synthetic for r in data.rows)}건",
        "- fold별 검증 행 수: " + ", ".join(f"{f}: {folds.count(f)}" for f in sorted(set(folds))), "",
        "## 모델 단독 (OOF, 임계값 적용)", "",
        *_table(["", "모델 신호", "신호 없음"], [["사기(suspicious+dangerous)", counts["tp"], counts["fn"]],
                                              ["정상(normal)", counts["fp"], counts["tn"]]]), "",
        f"- 사기 재현율 {_fmt(recall)}, 정밀도 {_fmt(precision)}. 임계값을 같은 OOF 점수로 골랐으므로 낙관적인 값이다.", "",
        "## 종합 판정 비교 (같은 dev 행, 모델 점수는 OOF)", "",
        "### rules", "", *_metrics_section("전체", rules_only),
        "### rules+model", "", *_metrics_section("전체", combined),
        f"#### 모델 신호로 판정이 바뀐 id ({len(raised)}건)", "",
    ]
    if raised:
        lines += _table(["id", "expected", "판정"], ([o.row.id, o.row.expected, o.predicted] for o in raised))
    lines.append("")
    return "\n".join(lines)


def train(data_path: Path, out_dir: Path, seed: int, n_splits: int, model_version: str,
          config: dict | None = None, timeout: float = 5.0,
          pipeline_factory: Callable[[dict, int], object] = build_pipeline) -> dict:
    import joblib

    config = config or DEFAULT_CONFIG
    if is_inside_repo(out_dir):
        raise TrainingError("모델 출력 폴더는 저장소 밖이어야 해요.")
    if (out_dir / MANIFEST_NAME).exists() or (out_dir / MODEL_FILE).exists():
        raise TrainingError("출력 폴더에 이미 모델이 있어요. 새 폴더를 지정해주세요.")
    data_sha = file_sha256(data_path)
    rows = load_rows(data_path)
    data = select_training_rows(rows)
    del rows  # test 행 원문을 더 들고 있지 않는다.
    if not data.rows:
        raise DatasetError("학습할 dev 행이 없어요.")
    scores, folds = cross_validate(data, config, seed, n_splits, pipeline_factory)
    threshold = choose_threshold(scores, data.labels)
    counts = model_counts(scores, data.labels, threshold)
    rules_only, combined = asyncio.run(oof_outcomes(data, scores, threshold, model_version, timeout))

    final = pipeline_factory(config, seed)
    final.fit(data.texts, data.labels)
    out_dir.mkdir(parents=True, exist_ok=True)
    # 임시 파일에 쓴 뒤 옮겨 반쯤 쓴 모델 파일이 남지 않게 한다.
    with tempfile.NamedTemporaryFile(dir=out_dir, suffix=".tmp", delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        joblib.dump(final, temp_path)
        temp_path.replace(out_dir / MODEL_FILE)
    finally:
        temp_path.unlink(missing_ok=True)
    commit, dirty = git_state(Path(__file__).resolve().parents[2])
    manifest = {
        "format": MANIFEST_FORMAT,
        "model_version": model_version,
        "model_file": MODEL_FILE,
        "model_sha256": file_sha256(out_dir / MODEL_FILE),
        # 임계값이 없으면 1.0으로 두고 threshold_found=false로 표시한다.
        "threshold": threshold if threshold is not None else 1.0,
        "threshold_found": threshold is not None,
        "threshold_status": THRESHOLD_STATUS,
        "threshold_rule": THRESHOLD_RULE,
        "label_mapping": {"positive": list(POSITIVE_LEVELS), "negative": list(NEGATIVE_LEVELS)},
        "text_preprocessing": "URL 구간을 '<URL>'로 치환 (app.model_adapter.prepare_model_text)",
        "seed": seed,
        "n_splits": n_splits,
        "cv": "StratifiedGroupKFold(campaign_id, shuffle=True)",
        "config": config,
        "data_file": data_path.name,
        "data_sha256": data_sha,
        "split_used": "dev",
        "counts": {"train_rows": len(data.rows), "positive": sum(data.labels), "negative": len(data.labels) - sum(data.labels),
                   "campaigns": len(set(data.groups)), "test_rows_dropped": data.test_rows_dropped, **data.excluded},
        "oof_model_counts": counts,
        "code_commit": commit,
        "worktree_dirty": dirty,
        "sklearn_version": _library_versions()["scikit-learn"],
        "libraries": _library_versions(),
        "created_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    (out_dir / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / REPORT_FILE).write_text(render_training_report(manifest, data, counts, folds, rules_only, combined) + "\n", encoding="utf-8")
    return manifest
