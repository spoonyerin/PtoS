import hashlib
import json
import logging

import pytest

from app.model_adapter import (
    MANIFEST_FORMAT, MODEL_PATH_ENV, REPO_ROOT, URL_PLACEHOLDER, JoblibTextModel, ModelLoadError,
    is_inside_repo, load_configured_model, prepare_model_text,
)
from app.urls import extract_urls


def write_model_dir(directory, payload=b"not a real model", **overrides):
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "model.joblib").write_bytes(payload)
    manifest = {
        "format": MANIFEST_FORMAT, "model_version": "fake-v1", "model_file": "model.joblib",
        "model_sha256": hashlib.sha256(payload).hexdigest(), "threshold": 0.5,
    } | overrides
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def test_prepare_model_text_replaces_url_codepoint_spans():
    content = "😀 확인 https://example.invalid/a 그리고 http://example.invalid 끝"
    text = prepare_model_text(content, extract_urls(content).spans)
    assert text == f"😀 확인 {URL_PLACEHOLDER} 그리고 {URL_PLACEHOLDER} 끝"
    assert prepare_model_text("주소 없음", []) == "주소 없음"


@pytest.mark.parametrize("env", [{}, {MODEL_PATH_ENV: ""}, {MODEL_PATH_ENV: "  "}])
def test_not_configured(env):
    assert load_configured_model(env).status == "not_configured"


def test_path_inside_repo_is_rejected():
    state = load_configured_model({MODEL_PATH_ENV: str(REPO_ROOT / "backend")})
    assert (state.status, state.reason) == ("load_failed", "MODEL_PATH_INSIDE_REPO")
    assert is_inside_repo(REPO_ROOT) and is_inside_repo(REPO_ROOT / "a" / "b")
    assert not is_inside_repo(REPO_ROOT.parent / (REPO_ROOT.name + "-models"))


@pytest.mark.parametrize("prepare,reason", [
    (lambda d: d / "missing", "MODEL_PATH_NOT_DIRECTORY"),
    (lambda d: (d.mkdir(), d)[1], "MANIFEST_MISSING"),
    (lambda d: (write_model_dir(d), (d / "manifest.json").write_text("{", encoding="utf-8"), d)[2], "MANIFEST_INVALID"),
    (lambda d: write_model_dir(d, format="other"), "MANIFEST_INVALID"),
    (lambda d: write_model_dir(d, model_file="../model.joblib"), "MANIFEST_INVALID"),
    (lambda d: write_model_dir(d, threshold=1.5), "MANIFEST_INVALID"),
    (lambda d: write_model_dir(d, threshold=True), "MANIFEST_INVALID"),
    (lambda d: write_model_dir(d, model_version=""), "MANIFEST_INVALID"),
    (lambda d: write_model_dir(d, model_file="other.joblib"), "MODEL_FILE_MISSING"),
    (lambda d: write_model_dir(d, model_sha256="0" * 64), "MODEL_SHA256_MISMATCH"),
    # SHA는 맞지만 joblib 파일이 아니다 (joblib 미설치여도 같은 코드).
    (lambda d: write_model_dir(d), "MODEL_LOAD_ERROR"),
])
def test_load_failures_are_reported_without_path(tmp_path, caplog, prepare, reason):
    directory = prepare(tmp_path / "model")
    with caplog.at_level(logging.INFO):
        state = load_configured_model({MODEL_PATH_ENV: str(directory)})
    assert (state.status, state.reason, state.model) == ("load_failed", reason, None)
    assert reason in caplog.text
    assert str(tmp_path) not in caplog.text


class FakePipeline:
    classes_ = [0, 1]

    def predict_proba(self, texts):
        return [[0.3, 0.7] for _ in texts]


def test_joblib_model_uses_positive_class_column():
    model = JoblibTextModel(FakePipeline(), "fake-v1", 0.5)
    assert model.score("텍스트") == pytest.approx(0.7)
    reordered = FakePipeline()
    reordered.classes_ = [1, 0]
    assert JoblibTextModel(reordered, "fake-v1", 0.5).score("텍스트") == pytest.approx(0.3)


def test_joblib_model_rejects_unexpected_interface():
    broken = FakePipeline()
    broken.classes_ = ["normal", "fraud"]
    with pytest.raises(ModelLoadError) as error:
        JoblibTextModel(broken, "fake-v1", 0.5)
    assert error.value.code == "MODEL_INTERFACE_INVALID"
    with pytest.raises(ModelLoadError):
        JoblibTextModel(object(), "fake-v1", 0.5)
