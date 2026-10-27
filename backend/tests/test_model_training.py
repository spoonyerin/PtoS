"""학습 스크립트 검증. 테스트 안에서 만든 합성 CSV만 쓴다. 탐지 성능 검증이 아니다."""

import asyncio
import csv
import json

import pytest

from app.analyzers import CompositeAnalyzer, RuleBasedAnalyzer
from app.contracts import AnalysisInput
from app.model_adapter import MODEL_PATH_ENV, REPO_ROOT, load_configured_model
from app.url_reputation import DisconnectedReputationProvider
from evaluation.harness import REQUIRED_COLUMNS, load_rows
from evaluation.model_training import (
    DEFAULT_CONFIG, THRESHOLD_STATUS, TrainingError, build_pipeline, choose_threshold, cross_validate,
    select_training_rows, train,
)

TEST_MARKER = "테스트분할전용문장"
FRAUD = ["[국세청] 미납 세금이 있어 오늘까지 납부하세요 http://example.invalid/{i}",
         "엄마 나 폰 고장났어 이 번호로 문자줘 급하게 돈 좀 보내줘 {i}",
         "택배 주소 불일치로 반송 예정입니다 아래 주소에서 확인 바랍니다 {i}"]
NORMAL = ["이번 주 토요일 모임은 공원에서 열립니다 {i}", "주문하신 책이 도서관에 도착했습니다 {i}"]


def write_csv(path, extra_rows=()):
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

    def __init__(self, config, seed):
        self._inner = build_pipeline(config, seed)

    @property
    def classes_(self):
        return self._inner.classes_

    def fit(self, texts, labels):
        SpyPipeline.seen.extend(texts)
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
    assert result.confidence is None and result.risk_level != "normal"
