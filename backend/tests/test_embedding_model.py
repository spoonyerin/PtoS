"""임베딩 모델(선택 기능)의 학습·저장·로드 검증. 가짜 인코더와 가짜 가중치 파일만 쓴다. 탐지 성능 검증이 아니다.

실제 인코더 확인은 선택 실행이다: torch·transformers가 있는 환경에서 PTOS_TEST_ENCODER_DIR에 로컬 인코더 폴더를 준다.
"""

import asyncio
import json
import os
from pathlib import Path

import pytest

import app.embedding_encoder as embedding_encoder
from app.analyzers import CompositeAnalyzer, RuleBasedAnalyzer
from app.contracts import AnalysisInput
from app.embedding_encoder import EncodedClassifier, EncoderUnavailable, weights_file
from app.model_adapter import MODEL_PATH_ENV, REPO_ROOT, load_configured_model
from evaluation.embedding_models import cached, embedding_candidate, embedding_manifest
from evaluation.model_training import train
from test_model_training import TEST_MARKER, write_csv


def fake_encode(texts):
    return [[float("납부" in t or "돈" in t or "반송" in t), len(t) / 100.0, 1.0] for t in texts]


@pytest.fixture
def encoder_dir(tmp_path):
    folder = tmp_path / "encoder"
    folder.mkdir()
    (folder / "model.safetensors").write_bytes(b"fake weights for tests")
    return folder


@pytest.fixture
def trained(tmp_path, encoder_dir):
    candidate = embedding_candidate("fake-embed", cached(fake_encode))
    out = tmp_path / "model"
    manifest = train(write_csv(tmp_path / "eval.csv"), out, seed=7, n_splits=4, model_version="embed-test-v1",
                     config=candidate["config"], pipeline_factory=candidate["factory"],
                     embedding=embedding_manifest("fake-embed", encoder_dir, "query: "))
    return out, manifest


def use_fake_encoder(monkeypatch, seen=None):
    def factory(model_dir, prefix="", batch_size=16, max_length=256):
        if seen is not None:
            seen.append((Path(model_dir), prefix, max_length))
        return fake_encode
    monkeypatch.setattr(embedding_encoder, "local_transformer_encoder", factory)


def rewrite(out, **changes):
    path = out / "manifest.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["embedding"] = {**manifest["embedding"], **changes}
    path.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")


def test_manifest_records_encoder_and_model_file_holds_only_the_classifier(trained, encoder_dir):
    out, manifest = trained
    embedding = manifest["embedding"]
    assert embedding["name"] == "fake-embed" and embedding["prefix"] == "query: " and embedding["max_length"] == 256
    assert embedding["weights_file"] == "model.safetensors" and len(embedding["weights_sha256"]) == 64
    assert Path(embedding["directory"]) == encoder_dir.resolve()
    assert manifest["config"]["embedding"] == "fake-embed" and manifest["counts"]["train_rows"] == 40
    import joblib
    stored = joblib.load(out / "model.joblib")
    assert type(stored).__name__ == "LogisticRegression"
    for output in ((out / "train-report.md").read_text(encoding="utf-8"), (out / "manifest.json").read_text(encoding="utf-8")):
        assert TEST_MARKER not in output and "example.invalid" not in output


def test_embedding_model_loads_with_the_recorded_encoder_and_runs_in_composite(trained, monkeypatch, encoder_dir):
    out, manifest = trained
    seen = []
    use_fake_encoder(monkeypatch, seen)
    state = load_configured_model({MODEL_PATH_ENV: str(out)})
    assert state.status == "loaded" and state.model.version == "embed-test-v1"
    assert seen == [(encoder_dir.resolve(), "query: ", 256)]
    assert 0.0 <= state.model.score("이번 주 토요일 모임은 공원에서 열립니다") <= 1.0
    analyzer = CompositeAnalyzer(RuleBasedAnalyzer(), state)
    result = asyncio.run(analyzer.analyze(AnalysisInput(input_type="text", content="이번 주 토요일 모임은 공원에서 열립니다")))
    assert result.analysis_stages[1].status == "completed" and result.confidence is None and result.risk_level != "normal"


def test_missing_torch_or_encoder_turns_the_model_stage_off_without_breaking_rules(trained, monkeypatch):
    out, _ = trained

    def unavailable(*args, **kwargs):
        raise EncoderUnavailable("no torch")

    monkeypatch.setattr(embedding_encoder, "local_transformer_encoder", unavailable)
    state = load_configured_model({MODEL_PATH_ENV: str(out)})
    assert (state.status, state.reason) == ("load_failed", "ENCODER_UNAVAILABLE")
    result = asyncio.run(CompositeAnalyzer(RuleBasedAnalyzer(), state).analyze(
        AnalysisInput(input_type="text", content="은행 담당자입니다. 인증번호를 알려주세요.")))
    assert result.risk_level == "dangerous" and result.analysis_stages[1].status == "unavailable"


@pytest.mark.parametrize("changes,reason", [
    ({"weights_sha256": "0" * 64}, "ENCODER_SHA256_MISMATCH"),
    ({"weights_file": "other.safetensors"}, "ENCODER_FILE_MISSING"),
    ({"weights_file": "../model.safetensors"}, "MANIFEST_INVALID"),
    ({"kind": "remote"}, "MANIFEST_INVALID"),
    ({"max_length": 100_000}, "MANIFEST_INVALID"),
    ({"prefix": 3}, "MANIFEST_INVALID"),
    ({"directory": str(REPO_ROOT / "eval-data" / "encoder")}, "MODEL_PATH_INSIDE_REPO"),
])
def test_encoder_is_refused_when_manifest_or_files_do_not_match(trained, monkeypatch, changes, reason):
    out, _ = trained
    use_fake_encoder(monkeypatch)
    rewrite(out, **changes)
    state = load_configured_model({MODEL_PATH_ENV: str(out)})
    assert (state.status, state.reason) == ("load_failed", reason)


def test_changed_encoder_weights_are_refused(trained, monkeypatch, encoder_dir):
    out, _ = trained
    use_fake_encoder(monkeypatch)
    (encoder_dir / "model.safetensors").write_bytes(b"replaced")
    assert load_configured_model({MODEL_PATH_ENV: str(out)}).reason == "ENCODER_SHA256_MISMATCH"


def test_weights_file_prefers_safetensors_and_reports_missing(tmp_path):
    with pytest.raises(EncoderUnavailable):
        weights_file(tmp_path)
    (tmp_path / "pytorch_model.bin").write_bytes(b"x")
    assert weights_file(tmp_path).name == "pytorch_model.bin"
    (tmp_path / "model.safetensors").write_bytes(b"x")
    assert weights_file(tmp_path).name == "model.safetensors"


def test_real_encoder_function_fails_cleanly_without_a_folder(tmp_path):
    # torch가 없으면 설치 안내, 있으면 폴더 없음 안내. 어느 쪽이든 경로를 메시지에 넣지 않는다.
    with pytest.raises(EncoderUnavailable) as error:
        embedding_encoder.local_transformer_encoder(tmp_path / "missing")
    assert str(tmp_path) not in str(error.value)


def test_encoded_classifier_passes_vectors_to_the_classifier():
    class Classifier:
        classes_ = [0, 1]

        def predict_proba(self, vectors):
            return [[1 - v[0], v[0]] for v in vectors]

    model = EncodedClassifier(Classifier(), fake_encode)
    assert model.classes_ == [0, 1] and model.predict_proba(["돈 보내"]) == [[0.0, 1.0]]


@pytest.mark.skipif(not os.environ.get("PTOS_TEST_ENCODER_DIR"), reason="실제 인코더 폴더(PTOS_TEST_ENCODER_DIR)와 torch·transformers 필요")
def test_real_encoder_gives_normalized_vectors_and_trains(tmp_path):
    folder = Path(os.environ["PTOS_TEST_ENCODER_DIR"])
    encode = embedding_encoder.local_transformer_encoder(folder, os.environ.get("PTOS_TEST_ENCODER_PREFIX", ""))
    first, second, again = encode(["내일 오후에 도서관에서 만나요.", "가짜기관입니다. 오늘까지 송금하세요."]) + encode(["내일 오후에 도서관에서 만나요."])
    assert len(first) == len(second) > 8 and abs(sum(v * v for v in first) - 1.0) < 1e-3
    assert max(abs(a - b) for a, b in zip(first, again)) < 1e-4 and first != second
    candidate = embedding_candidate("real-embed", cached(encode))
    out = tmp_path / "model"
    train(write_csv(tmp_path / "eval.csv"), out, seed=7, n_splits=4, model_version="real-embed-test",
          config=candidate["config"], pipeline_factory=candidate["factory"],
          embedding=embedding_manifest("real-embed", folder, os.environ.get("PTOS_TEST_ENCODER_PREFIX", "")))
    state = load_configured_model({MODEL_PATH_ENV: str(out)})
    assert state.status == "loaded" and 0.0 <= state.model.score("내일 오후에 도서관에서 만나요.") <= 1.0
