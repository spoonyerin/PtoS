"""학습 스크립트 검증. 테스트 안에서 만든 합성 CSV만 쓴다. 탐지 성능 검증이 아니다."""

import asyncio
import csv
import json

import pytest

from app.analyzers import CompositeAnalyzer, RuleBasedAnalyzer
from app.contracts import AnalysisInput
from app.model_adapter import MODEL_PATH_ENV, REPO_ROOT, load_configured_model
from app.url_reputation import DisconnectedReputationProvider
from evaluation.harness import BINARY_COLUMN, REQUIRED_COLUMNS, load_rows
from evaluation.model_training import (
    BINARY_LABEL_MAPPING, DEFAULT_CONFIG, POSITIVE_LEVELS, THRESHOLD_RULE, THRESHOLD_STATUS, TrainingError,
    build_pipeline, choose_threshold, cross_validate, select_training_rows, train,
)

TEST_MARKER = "테스트분할전용문장"
FRAUD = ["[국세청] 미납 세금이 있어 오늘까지 납부하세요 http://example.invalid/{i}",
         "엄마 나 폰 고장났어 이 번호로 문자줘 급하게 돈 좀 보내줘 {i}",
         "택배 주소 불일치로 반송 예정입니다 아래 주소에서 확인 바랍니다 {i}"]
NORMAL = ["이번 주 토요일 모임은 공원에서 열립니다 {i}", "주문하신 책이 도서관에 도착했습니다 {i}"]


def write_csv(path, extra_rows=(), binary_only=False):
    """binary_only=True면 dev 행의 expected_level을 비우고 expected_binary만 채운다."""
    path = _write_level_csv(path, extra_rows)
    if not binary_only:
        return path
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        if row["split"] == "dev" and BINARY_COLUMN not in row:
            level = row["expected_level"]
            row[BINARY_COLUMN] = "legit" if level == "normal" else "scam"
            row["expected_level"] = ""
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=(*REQUIRED_COLUMNS, BINARY_COLUMN), restval="")
        writer.writeheader()
        writer.writerows(rows)
    return path


def _write_level_csv(path, extra_rows=()):
    rows = []
    for c in range(12):
        for v in range(2):
            rows.append({"id": f"F{c}-{v}", "text": FRAUD[c % 3].format(i=c * 10 + v), "expected_level": "dangerous" if c % 2 else "suspicious",
                         "campaign_id": f"CF{c}", "split": "dev"})
    for c in range(8):
        for v in range(2):
            rows.append({"id": f"N{c}-{v}", "text": NORMAL[c % 2].format(i=c * 10 + v), "expected_level": "normal",
                         "campaign_id": f"CN{c}", "split": "dev"})
    for t in range(4):
        rows.append({"id": f"T{t}", "text": f"{TEST_MARKER} {FRAUD[t % 3].format(i=t)}", "expected_level": "dangerous",
                     "campaign_id": f"CT{t}", "split": "test"})
    rows += list(extra_rows)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=REQUIRED_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({"url": "", "label_reason": "합성", "source": "test", "is_synthetic": "true",
                             "review_status": "single"} | row)
    return path


class SpyPipeline:
    """실제 파이프라인을 감싸 학습·추론에 들어간 문장을 기록한다."""

    seen: list[str] = []
    fitted: list[str] = []

    def __init__(self, config, seed):
        self._inner = build_pipeline(config, seed)

    @property
    def classes_(self):
        return self._inner.classes_

    def fit(self, texts, labels):
        SpyPipeline.seen.extend(texts)
        SpyPipeline.fitted.extend(texts)
        self._inner.fit(texts, labels)
        return self

    def predict_proba(self, texts):
        SpyPipeline.seen.extend(texts)
        return self._inner.predict_proba(texts)


@pytest.fixture
def data_csv(tmp_path):
    return write_csv(tmp_path / "eval.csv")


def test_select_training_rows_uses_dev_only_and_binary_labels(tmp_path):
    extra = [{"id": "I1", "text": "정보 부족 라벨", "expected_level": "insufficient_information", "campaign_id": "CI", "split": "dev"},
             {"id": "E1", "text": "묶음 없는 정상 문장", "expected_level": "normal", "campaign_id": "", "split": "dev"}]
    data = select_training_rows(load_rows(write_csv(tmp_path / "eval.csv", extra)))
    assert data.test_rows_dropped == 4
    assert all(row.split == "dev" for row in data.rows)
    assert not any(TEST_MARKER in text for text in data.texts)
    assert data.excluded["insufficient_label"] == 1 and data.excluded["empty_campaign_id"] == 1
    assert sum(data.labels) == 24 and data.labels.count(0) == 17
    assert "row:E1" in data.groups
    assert all("http" not in text for text in data.texts)


def test_cross_validation_keeps_campaigns_in_one_fold(data_csv):
    data = select_training_rows(load_rows(data_csv))
    scores, folds = cross_validate(data, DEFAULT_CONFIG, 7, 4)
    assert len(scores) == len(data.rows) and all(0 <= s <= 1 for s in scores)
    assert set(folds) == {0, 1, 2, 3}
    by_group: dict[str, set[int]] = {}
    for group, fold in zip(data.groups, folds):
        by_group.setdefault(group, set()).add(fold)
    assert all(len(fold_set) == 1 for fold_set in by_group.values())


def test_cross_validation_rejects_too_few_campaigns(data_csv):
    data = select_training_rows(load_rows(data_csv))
    with pytest.raises(TrainingError):
        cross_validate(data, DEFAULT_CONFIG, 7, 9)


@pytest.mark.parametrize("scores,labels,expected", [
    ([0.9, 0.8, 0.4, 0.3, 0.2], [1, 1, 1, 0, 0], 0.4),
    ([0.9, 0.5, 0.6, 0.3], [1, 1, 0, 0], 0.9),
    ([0.5, 0.9], [1, 0], None),
    ([0.7, 0.7], [1, 0], None),
])
def test_threshold_never_flags_normal(scores, labels, expected):
    threshold = choose_threshold(scores, labels)
    assert threshold == expected
    if threshold is not None:
        assert not any(s >= threshold and y == 0 for s, y in zip(scores, labels))


def test_train_writes_model_outside_repo_without_test_rows_or_raw_text(data_csv, tmp_path):
    SpyPipeline.seen = []
    out = tmp_path / "models" / "v1"
    manifest = train(data_csv, out, seed=7, n_splits=4, model_version="test-v1", pipeline_factory=SpyPipeline)
    assert SpyPipeline.seen and not any(TEST_MARKER in text for text in SpyPipeline.seen)
    assert manifest["threshold_status"] == THRESHOLD_STATUS and manifest["split_used"] == "dev"
    assert manifest["counts"]["test_rows_dropped"] == 4 and manifest["counts"]["train_rows"] == 40
    assert manifest["seed"] == 7 and manifest["config"] == DEFAULT_CONFIG and len(manifest["data_sha256"]) == 64
    assert manifest["oof_model_counts"]["fp"] == 0
    stored = json.loads((out / "manifest.json").read_text(encoding="utf-8"))
    assert stored["model_sha256"] == manifest["model_sha256"]
    report = (out / "train-report.md").read_text(encoding="utf-8")
    for output in (report, (out / "manifest.json").read_text(encoding="utf-8")):
        assert TEST_MARKER not in output
        assert not any(NORMAL[0].split()[0] in line for line in output.splitlines())
        assert "example.invalid" not in output and "CF1" not in output
    assert "rules+model" in report and "탐지 성능 수치가 아니다" in report


def test_same_seed_gives_same_model_and_threshold(data_csv, tmp_path):
    first = train(data_csv, tmp_path / "a", seed=7, n_splits=4, model_version="test-v1")
    second = train(data_csv, tmp_path / "b", seed=7, n_splits=4, model_version="test-v1")
    for key in ("model_sha256", "threshold", "threshold_found", "oof_model_counts", "counts", "data_sha256"):
        assert first[key] == second[key]


def test_train_refuses_repo_or_existing_output(data_csv, tmp_path):
    with pytest.raises(TrainingError):
        train(data_csv, REPO_ROOT / "eval-data" / "model", seed=7, n_splits=4, model_version="test-v1")
    train(data_csv, tmp_path / "a", seed=7, n_splits=4, model_version="test-v1")
    with pytest.raises(TrainingError):
        train(data_csv, tmp_path / "a", seed=7, n_splits=4, model_version="test-v1")
    assert not (REPO_ROOT / "eval-data" / "model").exists()


def test_trained_model_loads_and_runs_in_composite(data_csv, tmp_path):
    out = tmp_path / "model"
    manifest = train(data_csv, out, seed=7, n_splits=4, model_version="test-v1")
    state = load_configured_model({MODEL_PATH_ENV: str(out)})
    assert state.status == "loaded" and state.model.version == "test-v1"
    assert state.model.threshold == (manifest["threshold"] if manifest["threshold_found"] else float("inf"))
    analyzer = CompositeAnalyzer(RuleBasedAnalyzer(DisconnectedReputationProvider("test")), state)
    result = asyncio.run(analyzer.analyze(AnalysisInput(input_type="text", content="이번 주 토요일 모임은 공원에서 열립니다")))
    assert result.analysis_stages[1].status == "completed"
    assert result.confidence is None and result.risk_level in ("normal", "insufficient_information")


# ---- 이진 라벨 기준(--labels binary, 선택 사항). 기본 levels 동작은 그대로여야 한다. ----

def test_binary_only_rows_are_skipped_by_default_and_used_with_binary_labels(tmp_path):
    rows = load_rows(write_csv(tmp_path / "eval.csv", binary_only=True))
    default = select_training_rows(rows)
    assert not default.rows and default.excluded["no_level_label"] == 40
    data = select_training_rows(rows, "binary")
    assert data.label_source == "binary" and "no_level_label" not in data.excluded
    assert sum(data.labels) == 24 and data.labels.count(0) == 16
    assert data.test_rows_dropped == 4 and not any(TEST_MARKER in text for text in data.texts)


def test_binary_labels_prefer_direct_value_and_skip_unlabeled_insufficient(tmp_path):
    extra = [{"id": "I1", "text": "정보 부족 라벨만 있는 문장", "expected_level": "insufficient_information", "campaign_id": "CI1", "split": "dev"},
             {"id": "I2", "text": "정보 부족이지만 이진 라벨이 있는 문장", "expected_level": "insufficient_information",
              BINARY_COLUMN: "legit", "campaign_id": "CI2", "split": "dev"}]
    path = _write_level_csv(tmp_path / "eval.csv")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    defaults = {"url": "", "label_reason": "합성", "source": "test", "is_synthetic": "true", "review_status": "single"}
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=(*REQUIRED_COLUMNS, BINARY_COLUMN), restval="")
        writer.writeheader()
        writer.writerows(rows + [defaults | row for row in extra])
    data = select_training_rows(load_rows(path), "binary")
    ids = [row.id for row in data.rows]
    assert "I1" not in ids and data.excluded["insufficient_label"] == 1
    assert data.labels[ids.index("I2")] == 0
    # 4단계 라벨에서 파생한 행도 같은 기준으로 들어간다.
    assert sum(data.labels) == 24 and data.labels.count(0) == 17


def test_unknown_label_source_is_rejected(data_csv):
    with pytest.raises(TrainingError):
        select_training_rows(load_rows(data_csv), "auto")


def test_default_manifest_keeps_level_label_mapping(data_csv, tmp_path):
    manifest = train(data_csv, tmp_path / "m", seed=7, n_splits=4, model_version="test-v1")
    assert "label_source" not in manifest and "label_source_counts" not in manifest
    assert manifest["label_mapping"] == {"positive": list(POSITIVE_LEVELS), "negative": ["normal"]}
    assert manifest["threshold_rule"] == THRESHOLD_RULE


def test_train_with_binary_labels_records_source_and_marks_dev_numbers(tmp_path):
    out = tmp_path / "model"
    manifest = train(write_csv(tmp_path / "eval.csv", binary_only=True), out, seed=7, n_splits=4,
                     model_version="test-bin-v1", label_source="binary")
    assert manifest["label_source"] == "binary" and manifest["label_mapping"] == BINARY_LABEL_MAPPING
    assert manifest["label_source_counts"] == {"direct": 40, "from_dangerous": 0, "from_suspicious": 0, "from_normal": 0}
    assert manifest["counts"]["train_rows"] == 40 and manifest["counts"]["test_rows_dropped"] == 4
    assert manifest["oof_model_counts"]["fp"] == 0 and "legit" in manifest["threshold_rule"]
    report = (out / "train-report.md").read_text(encoding="utf-8")
    assert "부풀려진 수치" in report and "이진 혼동행렬" in report and "라벨 기준: binary" in report
    assert "사기(scam)" in report and "suspicious+dangerous" not in report
    for output in (report, (out / "manifest.json").read_text(encoding="utf-8")):
        assert TEST_MARKER not in output and "example.invalid" not in output and "CF1" not in output
        assert not any(NORMAL[0].split()[0] in line for line in output.splitlines())
    state = load_configured_model({MODEL_PATH_ENV: str(out)})
    assert state.status == "loaded" and state.model.version == "test-bin-v1"


# ---- 학습에서 뺄 출처(--exclude-source). 뺀 행은 학습·교차검증·임계값에 쓰지 않고 채점만 한다. ----

HELD_MARKER = "학습제외출처전용문장"


def held_rows(count=6):
    return [{"id": f"H{i}", "text": f"{HELD_MARKER} {(FRAUD if i % 2 else NORMAL)[0].format(i=i)}",
             "expected_level": "dangerous" if i % 2 else "normal", "campaign_id": f"CH{i}", "split": "dev",
             "source": "FakeSet class=2 (합성)"} for i in range(count)]


def test_excluded_source_rows_are_held_out_of_training(tmp_path):
    rows = load_rows(write_csv(tmp_path / "eval.csv", held_rows()))
    everything = select_training_rows(rows)
    assert len(everything.rows) == 46 and everything.held_out is None and "excluded_source" not in everything.excluded
    data = select_training_rows(rows, exclude_sources=["fakeset", " "])
    assert len(data.rows) == 40 and data.excluded["excluded_source"] == 6 and data.excluded_sources == ("fakeset",)
    assert not any(HELD_MARKER in text for text in data.texts)
    assert [row.id for row in data.held_out.rows] == [f"H{i}" for i in range(6)]
    assert data.held_out.labels == [0, 1, 0, 1, 0, 1]


def test_train_never_fits_on_excluded_source_and_reports_it_separately(tmp_path):
    SpyPipeline.fitted = []
    out = tmp_path / "model"
    manifest = train(write_csv(tmp_path / "eval.csv", held_rows()), out, seed=7, n_splits=4, model_version="test-v1",
                     pipeline_factory=SpyPipeline, exclude_sources=["FakeSet"])
    assert SpyPipeline.fitted and not any(HELD_MARKER in text for text in SpyPipeline.fitted)
    assert manifest["counts"]["train_rows"] == 40 and manifest["counts"]["excluded_source"] == 6
    assert manifest["excluded_sources"] == ["fakeset"]
    held = manifest["held_out_model_counts"]
    assert held["tp"] + held["fn"] == 3 and held["fp"] + held["tn"] == 3
    report = (out / "train-report.md").read_text(encoding="utf-8")
    assert "학습에서 뺀 출처 행" in report and "두 값을 섞어 말하지 않는다" in report
    assert HELD_MARKER not in report and HELD_MARKER not in (out / "manifest.json").read_text(encoding="utf-8")


def test_default_manifest_has_no_excluded_source_keys(data_csv, tmp_path):
    manifest = train(data_csv, tmp_path / "m", seed=7, n_splits=4, model_version="test-v1")
    assert "excluded_sources" not in manifest and "held_out_model_counts" not in manifest
    assert "학습에서 뺀 출처 행" not in (tmp_path / "m" / "train-report.md").read_text(encoding="utf-8")
