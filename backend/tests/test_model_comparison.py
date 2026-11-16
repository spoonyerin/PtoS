"""모델 후보 비교 도구의 동작 검증. 테스트 안에서 만든 합성 CSV만 쓴다. 수치 자체는 탐지 성능이 아니다."""

import pytest

import compare_models
from app.model_adapter import REPO_ROOT
from evaluation.harness import DatasetError
from evaluation.model_comparison import BASELINE, CANDIDATES, build_candidate, compare, render_comparison_report
from evaluation.model_training import DEFAULT_CONFIG, TrainingError
from test_model_training import NORMAL, TEST_MARKER, write_csv


@pytest.fixture
def data_csv(tmp_path):
    return write_csv(tmp_path / "eval.csv")


class SpyCandidate:
    """후보 파이프라인을 감싸 학습·추론에 들어간 문장을 기록한다."""

    seen: list[str] = []

    def __init__(self, config, seed):
        self._inner = build_candidate(config, seed)

    @property
    def classes_(self):
        return self._inner.classes_

    def fit(self, texts, labels):
        SpyCandidate.seen.extend(texts)
        self._inner.fit(texts, labels)
        return self

    def predict_proba(self, texts):
        SpyCandidate.seen.extend(texts)
        return self._inner.predict_proba(texts)


def test_baseline_candidate_is_the_training_default():
    assert CANDIDATES[BASELINE]["config"] == DEFAULT_CONFIG and next(iter(CANDIDATES)) == BASELINE


def test_compare_runs_every_candidate_on_dev_rows_only(data_csv):
    SpyCandidate.seen = []
    result = compare(data_csv, seed=7, n_splits=4, pipeline_factory=SpyCandidate)
    assert [c.name for c in result.candidates] == list(CANDIDATES)
    assert SpyCandidate.seen and not any(TEST_MARKER in text for text in SpyCandidate.seen)
    assert result.data.test_rows_dropped == 4 and len(result.data.rows) == 40
    assert result.rules_only.scam_total == 24 and result.rules_only.legit_total == 16
    for candidate in result.candidates:
        counts = candidate.counts
        assert counts["tp"] + counts["fn"] == 24 and counts["fp"] + counts["tn"] == 16
        # 임계값 기준: 정상 라벨 행에는 모델 신호가 없다.
        assert counts["fp"] == 0
        assert 0 <= candidate.roc_auc <= 1 and 0 <= candidate.average_precision <= 1
        combined = candidate.combined
        assert combined.total == 40 and combined.errors == 0
        # 모델은 판정을 올릴 수만 있다: 규칙만일 때보다 경고가 줄지 않고, 올라간 만큼만 늘어난다.
        added = combined.scam_warned + combined.legit_flagged - result.rules_only.scam_warned - result.rules_only.legit_flagged
        assert added == candidate.raised >= 0
        assert combined.scam_dangerous == result.rules_only.scam_dangerous
        assert combined.legit_dangerous == result.rules_only.legit_dangerous


def test_same_seed_gives_same_comparison(data_csv):
    first = compare(data_csv, seed=7, n_splits=4)
    second = compare(data_csv, seed=7, n_splits=4)
    for a, b in zip(first.candidates, second.candidates):
        assert (a.threshold, a.counts, a.roc_auc, a.average_precision, a.raised) == (
            b.threshold, b.counts, b.roc_auc, b.average_precision, b.raised)


def test_report_has_aggregates_only_and_marks_dev_numbers(data_csv):
    report = render_comparison_report(compare(data_csv, seed=7, n_splits=4, names=[BASELINE, "tfidf-word-1-2-lr"]))
    assert "부풀려진 수치" in report and "탐지 성능 수치가 아니다" in report and "팀이 정한다" in report
    assert f"| rules+{BASELINE} |" in report and "| rules |" in report and "tfidf-char_wb-2-4-nb" not in report
    assert TEST_MARKER not in report and "example.invalid" not in report
    assert not any(NORMAL[0].split()[0] in line for line in report.splitlines())
    # 행 id와 campaign 값도 넣지 않는다.
    assert "F1-0" not in report and "N1-0" not in report and "CF1" not in report and "CN1" not in report


def test_binary_labels_use_binary_only_rows(tmp_path):
    path = write_csv(tmp_path / "eval.csv", binary_only=True)
    with pytest.raises(DatasetError):
        compare(path, seed=7, n_splits=4, names=[BASELINE])
    result = compare(path, seed=7, n_splits=4, label_source="binary", names=[BASELINE])
    assert len(result.data.rows) == 40 and result.info["label_source"] == "binary"
    assert "| 라벨 기준 | binary |" in render_comparison_report(result)


@pytest.mark.parametrize("names", [["no-such-model"], [BASELINE, BASELINE]])
def test_unknown_or_repeated_candidate_is_rejected(data_csv, names):
    with pytest.raises(TrainingError):
        compare(data_csv, seed=7, n_splits=4, names=names)


def test_cli_writes_report_outside_repo_only(data_csv, tmp_path, capsys):
    out = tmp_path / "reports" / "compare.md"
    base = ["--data", str(data_csv), "--seed", "7", "--n-splits", "4", "--candidates", BASELINE]
    assert compare_models.main([*base, "--output", str(out)]) == 0
    assert "모델 단독 (OOF)" in out.read_text(encoding="utf-8")
    assert not list(tmp_path.rglob("*.joblib"))
    inside = REPO_ROOT / "eval-reports" / "compare.md"
    assert compare_models.main([*base, "--output", str(inside)]) == 1
    assert not inside.exists()
    assert compare_models.main([*base, "--n-splits", "9"]) == 1
    err = capsys.readouterr().err
    assert "저장소 밖" in err and "fold 수" in err and str(tmp_path) not in err
