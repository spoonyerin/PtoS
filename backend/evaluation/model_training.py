"""TF-IDF 문자 n-gram + 로지스틱 회귀 기준선 학습 (T5, 개발용).

- split=dev 행만 학습·임계값 결정에 쓴다. test 행은 읽은 직후 버리고 건수만 기록한다.
- dev 안에서 campaign_id 기준 층화 그룹 교차검증으로 out-of-fold(OOF) 점수를 내고, 임계값은 OOF 점수로만 정한다.
- 임계값 기준(임시, 팀 확정 필요): expected=normal 행이 모델 신호로 표시되는 경우 0건을 지키면서 사기 재현율 최대.
- 모델 파일·manifest·리포트는 저장소 밖에만 쓴다. 리포트에는 id와 집계만 넣고 원문을 넣지 않는다.
- 라벨 기준은 기본 levels(4단계 라벨)다. binary는 선택 사항이며 이진 라벨(expected_binary 우선, 없으면 4단계에서 파생)을 쓴다.
  어느 기준을 쓸지는 팀 확정이 필요하다(임시).
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

from .harness import (
    BINARY_SOURCES, DatasetError, EvalRow, Outcome, _analyze_one, _binary_section, _metrics_section, _table,
    binary_label, git_state, load_rows,
)

MODEL_FILE = "model.joblib"
REPORT_FILE = "train-report.md"
THRESHOLD_STATUS = "provisional-dev-cv"
THRESHOLD_RULE = "OOF 점수에서 expected=normal 행 모델 신호 0건을 지키며 사기 재현율 최대 (임시, 팀 확정 필요)"
POSITIVE_LEVELS = (RiskLevel.SUSPICIOUS.value, RiskLevel.DANGEROUS.value)
NEGATIVE_LEVELS = (RiskLevel.NORMAL.value,)
# 학습 라벨 기준. levels가 기본이고 binary는 명시적으로 고를 때만 쓴다(임시, 팀 확정 필요).
LABEL_SOURCES = ("levels", "binary")
BINARY_THRESHOLD_RULE = "OOF 점수에서 정상(legit) 라벨 행 모델 신호 0건을 지키며 사기 재현율 최대 (임시, 팀 확정 필요)"
BINARY_LABEL_MAPPING = {"positive": ["scam"], "negative": ["legit"],
                        "source": "expected_binary 우선, 비어 있으면 expected_level에서 파생 (dangerous·suspicious → scam, normal → legit)"}
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
    label_source: str = "levels"
    # 학습에서 뺀 출처의 dev 행. 학습·교차검증·임계값에 쓰지 않고, 다 학습한 모델로 채점만 한다.
    held_out: "TrainingSet | None" = None
    excluded_sources: tuple[str, ...] = ()


def _training_label(row: EvalRow, label_source: str, excluded: dict[str, int]) -> int | None:
    """학습 라벨(사기 1, 정상 0). 쓸 수 없는 행은 제외 건수만 올리고 None."""
    if label_source == "binary":
        binary, _ = binary_label(row)
        if binary is None:
            excluded["insufficient_label"] += 1
            return None
        return 1 if binary == "scam" else 0
    if row.expected is None:
        # 이진 라벨만 있는 행. 기본 라벨 기준은 4단계 라벨이라 쓰지 않는다.
        # 이런 행이 없는 CSV의 리포트·manifest가 그대로이도록 있을 때만 키를 만든다.
        excluded["no_level_label"] = excluded.get("no_level_label", 0) + 1
        return None
    if row.expected in POSITIVE_LEVELS:
        return 1
    if row.expected in NEGATIVE_LEVELS:
        return 0
    excluded["insufficient_label"] += 1
    return None


def select_training_rows(rows: list[EvalRow], label_source: str = "levels",
                         exclude_sources: tuple[str, ...] | list[str] = ()) -> TrainingSet:
    """exclude_sources: source 열에 이 글자가 들어 있는 행(대소문자 무시)은 학습에서 빼고 held_out에 둔다."""
    if label_source not in LABEL_SOURCES:
        raise TrainingError(f"라벨 기준은 {'/'.join(LABEL_SOURCES)} 중 하나여야 해요.")
    needles = tuple(dict.fromkeys(value.strip().casefold() for value in exclude_sources if value.strip()))
    held = TrainingSet([], [], [], [], label_source=label_source) if needles else None
    dev = [row for row in rows if row.split == "dev"]
    excluded = {"url_input": 0, "insufficient_label": 0, "url_extraction_error": 0, "empty_campaign_id": 0}
    selected, texts, labels, groups = [], [], [], []
    for row in dev:
        if row.input_type != "text":
            excluded["url_input"] += 1
            continue
        label = _training_label(row, label_source, excluded)
        if label is None:
            continue
        try:
            spans = extract_urls(row.content).spans
        except UrlInputError:
            excluded["url_extraction_error"] += 1
            continue
        if not row.campaign_id:
            # 묶음 정보가 없으면 행 하나를 하나의 묶음으로 본다.
            excluded["empty_campaign_id"] += 1
        target = TrainingSet(selected, texts, labels, groups)
        if held is not None and any(needle in row.source.casefold() for needle in needles):
            excluded["excluded_source"] = excluded.get("excluded_source", 0) + 1
            target = held
        target.rows.append(row)
        target.texts.append(prepare_model_text(row.content, spans))
        target.labels.append(label)
        target.groups.append(row.campaign_id or f"row:{row.id}")
    return TrainingSet(selected, texts, labels, groups, len(rows) - len(dev), excluded, label_source, held, needles)


def score_texts(pipeline, texts: list[str]) -> list[float]:
    if not texts:
        return []
    positive = list(pipeline.classes_).index(1)
    return [float(proba[positive]) for proba in pipeline.predict_proba(texts)]


def label_source_counts(data: TrainingSet) -> dict[str, int]:
    """이진 라벨 출처별 학습 행 수. suspicious에서 파생한 scam은 정답이 불확실하다."""
    return {source: sum(binary_label(row)[1] == source for row in data.rows) for source in BINARY_SOURCES}


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


def _held_out_report(data: TrainingSet, held: dict, section) -> list[str]:
    """학습에서 뺀 출처 행의 집계. 이 행들은 학습·임계값에 쓰지 않았다."""
    counts = held["counts"]
    lines = [
        "## 학습에서 뺀 출처 행 (학습·임계값에 쓰지 않음, 다 학습한 모델로 채점)", "",
        f"- 뺀 기준(source 열에 포함된 글자): {', '.join(data.excluded_sources)}",
        f"- {len(data.held_out.rows)}건 (사기 {sum(data.held_out.labels)}, 정상 {len(data.held_out.labels) - sum(data.held_out.labels)})",
        "- 위 OOF 수치는 학습에 쓴 행만의 값이고, 아래는 학습에 쓰지 않은 행만의 값이다. 두 값을 섞어 말하지 않는다.",
        "- **(dev, 부풀려진 수치)** 학습에는 쓰지 않았지만 규칙 보강에는 쓴 dev 행이다.", "",
        *_table(["", "모델 신호", "신호 없음"], [["사기", counts["tp"], counts["fn"]], ["정상", counts["fp"], counts["tn"]]]), "",
        "### rules", "", *section("학습에서 뺀 행", held["rules_only"]),
        "### rules+model", "", *section("학습에서 뺀 행", held["combined"]),
    ]
    return lines


def render_training_report(manifest: dict, data: TrainingSet, counts: dict[str, int],
                           folds: list[int], rules_only: list[Outcome], combined: list[Outcome],
                           held: dict | None = None) -> str:
    recall = counts["tp"] / (counts["tp"] + counts["fn"]) if counts["tp"] + counts["fn"] else None
    precision = counts["tp"] / (counts["tp"] + counts["fp"]) if counts["tp"] + counts["fp"] else None
    raised = [c for r, c in zip(rules_only, combined) if r.predicted != c.predicted]
    binary = data.label_source == "binary"
    positive_name, negative_name = ("사기(scam)", "정상(legit)") if binary else ("사기(suspicious+dangerous)", "정상(normal)")
    section = _binary_section if binary else _metrics_section
    binary_notes = [
        "**(dev, 학습과 임계값 결정에 쓴 데이터라 부풀려진 수치)** 다른 평가 CSV·다른 라벨 기준의 수치와 비교하지 않는다.", "",
    ] if binary else []
    binary_data_lines = [
        "- 라벨 기준: binary (expected_binary 우선, 비어 있으면 expected_level에서 파생. 임시, 팀 확정 필요)",
        "- 라벨 출처: " + ", ".join(f"{BINARY_SOURCES[source]} {count}" for source, count in label_source_counts(data).items())
        + ". suspicious에서 파생한 scam은 정답이 불확실하다.",
    ] if binary else []
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
        *binary_notes,
        "## 데이터", "",
        *binary_data_lines,
        f"- 학습에 쓴 dev 행: {len(data.rows)}건 (사기 {sum(data.labels)}, 정상 {len(data.labels) - sum(data.labels)}), campaign {len(set(data.groups))}개",
        f"- test 행: {data.test_rows_dropped}건은 읽은 직후 버렸고 학습·임계값에 쓰지 않았다.",
        "- 제외: " + ", ".join(f"{k} {v}" for k, v in data.excluded.items()),
        f"- 합성 {sum(r.is_synthetic for r in data.rows)}건, 실제 {sum(not r.is_synthetic for r in data.rows)}건",
        "- fold별 검증 행 수: " + ", ".join(f"{f}: {folds.count(f)}" for f in sorted(set(folds))), "",
        "## 모델 단독 (OOF, 임계값 적용)", "",
        *_table(["", "모델 신호", "신호 없음"], [[positive_name, counts["tp"], counts["fn"]],
                                              [negative_name, counts["fp"], counts["tn"]]]), "",
        f"- 사기 재현율 {_fmt(recall)}, 정밀도 {_fmt(precision)}. 임계값을 같은 OOF 점수로 골랐으므로 낙관적인 값이다.", "",
        "## 종합 판정 비교 (같은 dev 행, 모델 점수는 OOF)", "",
        "### rules", "", *section("전체", rules_only),
        "### rules+model", "", *section("전체", combined),
        f"#### 모델 신호로 판정이 바뀐 id ({len(raised)}건)", "",
    ]
    if raised:
        lines += _table(["id", "expected", "판정"], (
            [o.row.id, binary_label(o.row)[0] if binary else o.row.expected, o.predicted] for o in raised))
    lines.append("")
    if held:
        lines += _held_out_report(data, held, section)
    return "\n".join(lines)


def train(data_path: Path, out_dir: Path, seed: int, n_splits: int, model_version: str,
          config: dict | None = None, timeout: float = 5.0,
          pipeline_factory: Callable[[dict, int], object] = build_pipeline, label_source: str = "levels",
          exclude_sources: tuple[str, ...] | list[str] = (), embedding: dict | None = None) -> dict:
    """embedding: 임베딩 후보로 학습할 때 manifest에 적을 인코더 정보(evaluation.embedding_models.embedding_manifest)."""
    import joblib

    config = config or DEFAULT_CONFIG
    if is_inside_repo(out_dir):
        raise TrainingError("모델 출력 폴더는 저장소 밖이어야 해요.")
    if (out_dir / MANIFEST_NAME).exists() or (out_dir / MODEL_FILE).exists():
        raise TrainingError("출력 폴더에 이미 모델이 있어요. 새 폴더를 지정해주세요.")
    data_sha = file_sha256(data_path)
    rows = load_rows(data_path)
    data = select_training_rows(rows, label_source, exclude_sources)
    del rows  # test 행 원문을 더 들고 있지 않는다.
    if not data.rows:
        raise DatasetError("학습할 dev 행이 없어요.")
    scores, folds = cross_validate(data, config, seed, n_splits, pipeline_factory)
    threshold = choose_threshold(scores, data.labels)
    counts = model_counts(scores, data.labels, threshold)
    rules_only, combined = asyncio.run(oof_outcomes(data, scores, threshold, model_version, timeout))

    final = pipeline_factory(config, seed)
    final.fit(data.texts, data.labels)
    held = None
    if data.held_out is not None and data.held_out.rows:
        # 학습에서 뺀 출처 행은 다 학습한 모델로 채점만 한다. 임계값은 위에서 학습 행만으로 이미 정했다.
        held_scores = score_texts(final, data.held_out.texts)
        held_rules, held_combined = asyncio.run(oof_outcomes(data.held_out, held_scores, threshold, model_version, timeout))
        held = {"counts": model_counts(held_scores, data.held_out.labels, threshold),
                "rules_only": held_rules, "combined": held_combined}
    out_dir.mkdir(parents=True, exist_ok=True)
    # 임시 파일에 쓴 뒤 옮겨 반쯤 쓴 모델 파일이 남지 않게 한다.
    with tempfile.NamedTemporaryFile(dir=out_dir, suffix=".tmp", delete=False) as handle:
        temp_path = Path(handle.name)
    try:
        # 임베딩 후보는 인코더를 뺀 분류기만 저장한다. 인코더는 manifest의 로컬 폴더에서 다시 읽는다.
        joblib.dump(final.export() if hasattr(final, "export") else final, temp_path)
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
    if label_source == "binary":
        # 기본(levels) manifest가 그대로이도록 binary일 때만 값을 바꾸고 키를 더한다.
        manifest |= {"threshold_rule": BINARY_THRESHOLD_RULE, "label_mapping": BINARY_LABEL_MAPPING,
                     "label_source": label_source, "label_source_counts": label_source_counts(data)}
    if embedding:
        manifest |= {"embedding": embedding,
                     "text_preprocessing": manifest["text_preprocessing"] + ", 그 뒤 고정 인코더로 임베딩"}
    if data.excluded_sources:
        manifest |= {"excluded_sources": list(data.excluded_sources),
                     "held_out_model_counts": held["counts"] if held else None}
    (out_dir / MANIFEST_NAME).write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (out_dir / REPORT_FILE).write_text(render_training_report(manifest, data, counts, folds, rules_only, combined, held) + "\n", encoding="utf-8")
    return manifest
