"""하네스의 rules+model 등록. 가짜 모델과 테스트 안 합성 CSV만 쓴다. 탐지 성능 검증이 아니다."""

import os
import subprocess
import sys
from pathlib import Path

import pytest

from app.analyzers import CompositeAnalyzer, RuleBasedAnalyzer
from app.model_adapter import MODEL_PATH_ENV, ModelState
from app.url_reputation import DisconnectedReputationProvider
from evaluation.harness import ANALYZERS, AnalyzerSetupError, file_sha256, run
from evaluation.model_training import train
from test_model_training import TEST_MARKER, write_csv

BACKEND = Path(__file__).resolve().parents[1]


class FakeModel:
    version = "fake-v1"
    threshold = 0.5

    def __init__(self, info):
        self.info = info

    def score(self, text):
        return 0.9


def composite_factory(info):
    return lambda: CompositeAnalyzer(RuleBasedAnalyzer(DisconnectedReputationProvider("test")), ModelState("loaded", FakeModel(info)))


def test_rules_model_requires_loaded_model(monkeypatch, tmp_path):
    assert "rules+model" in ANALYZERS
    monkeypatch.delenv(MODEL_PATH_ENV, raising=False)
    path = write_csv(tmp_path / "eval.csv")
    with pytest.raises(AnalyzerSetupError, match="not_configured"):
        run(path, "rules+model", split="dev")
    monkeypatch.setenv(MODEL_PATH_ENV, str(tmp_path / "missing"))
    with pytest.raises(AnalyzerSetupError, match="MODEL_PATH_NOT_DIRECTORY") as error:
        run(path, "rules+model", split="dev")
    assert str(tmp_path) not in str(error.value)


def test_report_shows_model_info_stage_counts_and_in_sample_warning(tmp_path):
    path = write_csv(tmp_path / "eval.csv")
    info = {"model_sha256": "a" * 64, "data_sha256": file_sha256(path), "threshold_status": "provisional-dev-cv"}
    report = run(path, "rules+model", analyzers={"rules+model": composite_factory(info)}, split="dev")
    assert "| 모델 버전 | fake-v1 |" in report and "a" * 64 in report and "provisional-dev-cv" in report
    assert "- 모델 단계 상태: completed 40" in report
    assert "in-sample" in report and "rules-model-dev-v1" in report
    assert TEST_MARKER not in report
    test_report = run(path, "rules+model", analyzers={"rules+model": composite_factory(info)}, split="test")
    assert "in-sample" not in test_report and "completed 4" in test_report
    other = run(path, "rules+model", analyzers={"rules+model": composite_factory(info | {"data_sha256": "b" * 64})}, split="dev")
    assert "SHA-256이 다른 CSV로 학습" in other and "in-sample" not in other


def test_rules_report_has_no_model_section(tmp_path):
    report = run(write_csv(tmp_path / "eval.csv"), "rules", split="dev")
    assert "모델 단계 상태" not in report and "모델 버전" not in report


def test_rules_model_with_trained_model(monkeypatch, tmp_path):
    path = write_csv(tmp_path / "eval.csv")
    manifest = train(path, tmp_path / "model", seed=7, n_splits=4, model_version="test-v1")
    monkeypatch.setenv(MODEL_PATH_ENV, str(tmp_path / "model"))
    report = run(path, "rules+model", split="dev")
    assert manifest["model_sha256"] in report and "| 모델 버전 | test-v1 |" in report
    assert "completed 40" in report and "in-sample" in report
    assert TEST_MARKER not in report and "example.invalid" not in report


def test_cli_reports_missing_model_without_traceback(tmp_path):
    path = write_csv(tmp_path / "eval.csv")
    env = {key: value for key, value in os.environ.items() if key != MODEL_PATH_ENV}
    completed = subprocess.run(
        [sys.executable, "evaluate.py", "--data", str(path), "--analyzer", "rules+model", "--split", "dev"],
        cwd=BACKEND, capture_output=True, text=True, encoding="utf-8", env=env,
    )
    assert completed.returncode != 0
    assert "분석기 준비 오류" in completed.stderr and "Traceback" not in completed.stderr
