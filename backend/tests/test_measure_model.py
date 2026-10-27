"""측정 스크립트의 동작 검증. 테스트 안 합성 CSV로 학습한 모델만 쓴다. 측정값 자체는 검증하지 않는다."""

import pytest

import measure_model
from evaluation.model_training import train
from test_model_training import TEST_MARKER, write_csv


@pytest.fixture
def trained(tmp_path):
    path = write_csv(tmp_path / "eval.csv")
    train(path, tmp_path / "model", seed=7, n_splits=4, model_version="test-v1")
    return path, tmp_path / "model"


def test_measure_reports_aggregates_without_raw_text(trained):
    data, model_dir = trained
    result = measure_model.measure(model_dir, data, repeat=2)
    assert result["model_version"] == "test-v1" and result["load_seconds"] > 0
    assert result["traced_peak_bytes"] > 0 and result["model_file_bytes"] > 0
    assert result["latency_ms"]["dev text 행"]["inputs"] == 40
    for group in result["latency_ms"].values():
        assert {"model.score", "rules", "rules+model"} <= group.keys()
        assert all(group[key]["p50"] <= group[key]["max"] for key in ("model.score", "rules", "rules+model"))
    report = measure_model.render(result)
    assert "성능 보장이나 제품 목표" in report and "| dev text 행 | 40 | model.score |" in report
    assert TEST_MARKER not in report and "example.invalid" not in report and "가짜 측정 문장" not in report


def test_cli_without_model_or_with_bad_model(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv(measure_model.MODEL_PATH_ENV, raising=False)
    assert measure_model.main([]) == 2
    assert measure_model.main(["--model-dir", str(tmp_path / "missing")]) == 1
    err = capsys.readouterr().err
    assert "MODEL_PATH_NOT_DIRECTORY" in err and str(tmp_path) not in err


def test_cli_writes_output(trained, tmp_path):
    _, model_dir = trained
    out = tmp_path / "measure.md"
    assert measure_model.main(["--model-dir", str(model_dir), "--repeat", "1", "--output", str(out)]) == 0
    assert "로드 시간" in out.read_text(encoding="utf-8")


def test_percentile():
    assert measure_model.percentile([3.0, 1.0, 2.0, 4.0], 0.5) == 2.0
    assert measure_model.percentile([1.0] * 19 + [9.0], 0.95) == 1.0
    assert measure_model.percentile([5.0], 0.95) == 5.0
