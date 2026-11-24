"""학습 전용 데이터 학습·비교와 미세조정 모델 로더 검증. 테스트 안에서 만든 합성 CSV와 가짜 모델만 쓴다.

탐지 성능 검증이 아니다. 실제 인코더·미세조정 학습은 자동 테스트에서 돌리지 않는다.
"""

import csv
import hashlib
import json

import pytest

import app.transformer_model as transformer_model
from app.model_adapter import (
    MANIFEST_FORMAT, MODEL_PATH_ENV, NUMBER_PLACEHOLDER, PHONE_PLACEHOLDER, load_configured_model, mask_numbers,
)
from evaluation.external_training import (
    Candidate, ExternalDataError, choose_threshold_at_rate, crossfit_thresholds, family, load_dev, load_external, rank,
    run_candidate,
)
from evaluation.model_training import DEFAULT_CONFIG, TrainingError, build_pipeline, choose_threshold
from test_model_training import FRAUD, NORMAL, write_csv


def write_external(path, n=12):
    rows = [{"text": t.format(i=i), "label": 1, "source": "SYNSCAM"} for i in range(n) for t in FRAUD]
    rows += [{"text": t.format(i=i), "label": 0, "source": "SYNLEGIT"} for i in range(n) for t in NORMAL]
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["text", "label", "source"])
        writer.writeheader()
        writer.writerows(rows)
    return path


def test_mask_numbers_matches_training_placeholders():
    assert mask_numbers("문의 010-1234-5678 또는 1588-1234") == f"문의 {PHONE_PLACEHOLDER} 또는 {PHONE_PLACEHOLDER}"
    assert mask_numbers("계좌 123-4567-890123 입금") == f"계좌 {NUMBER_PLACEHOLDER} 입금"
    assert mask_numbers("오늘 3시 12,000원") == "오늘 3시 12,000원"


def test_load_external_masks_and_replaces_urls(tmp_path):
    path = tmp_path / "train.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["text", "label", "source"])
        writer.writerow(["확인 https://example.invalid/a 문의 010-1234-5678", "1", "X"])
        writer.writerow(["안녕하세요", "0", "Y"])
        writer.writerow(["라벨 없음", "", "Y"])
    data = load_external(path)
    assert data.texts == [f"확인 <URL> 문의 {PHONE_PLACEHOLDER}", "안녕하세요"]
    assert data.labels == [1, 0] and data.skipped == 1


def test_load_external_requires_both_labels_and_columns(tmp_path):
    path = tmp_path / "one.csv"
    path.write_text("text,label,source\n문장,1,X\n", encoding="utf-8")
    with pytest.raises(ExternalDataError):
        load_external(path)
    bad = tmp_path / "bad.csv"
    bad.write_text("text,label\n문장,1\n", encoding="utf-8")
    with pytest.raises(ExternalDataError):
        load_external(bad)


def test_crossfit_thresholds_never_use_the_row_own_fold():
    scores = [0.9, 0.8, 0.1, 0.2] * 5
    labels = [1, 1, 0, 0] * 5
    groups = [f"g{i}" for i in range(20)]
    thresholds, normals, folds = crossfit_thresholds(scores, labels, groups, seed=1, n_splits=5)
    assert sorted(set(folds)) == [0, 1, 2, 3, 4]
    assert all(t is not None and 0.2 < t <= 0.8 for t in thresholds)
    assert all(n == 0.8 for n in normals)


def test_threshold_at_rate_zero_matches_strict_rule_and_allows_top_legit():
    scores = [0.95, 0.9, 0.8, 0.7, 0.85, 0.6, 0.5, 0.4, 0.3, 0.2]
    labels = [1, 1, 1, 1, 0, 0, 0, 0, 0, 0]
    assert choose_threshold_at_rate(scores, labels, 0.0) == choose_threshold(scores, labels) == 0.9
    # 정상 6건의 20% → 1건 허용: 정상 최고점(0.85)은 신호가 나도 되고, 그다음 정상(0.6)보다 큰 사기 최솟값
    assert choose_threshold_at_rate(scores, labels, 0.2) == 0.7
    with pytest.raises(ValueError):
        choose_threshold_at_rate(scores, labels, 1.0)


def test_export_with_legit_signal_rate_rewrites_thresholds(tmp_path):
    import export_external_model
    from train_external import _joblib_export
    train = load_external(write_external(tmp_path / "train.csv"))
    dev = load_dev(write_csv(tmp_path / "eval.csv", binary_only=True))
    candidate = Candidate("tfidf-lr", "테스트", lambda seed: build_pipeline(DEFAULT_CONFIG, seed), _joblib_export)
    run_candidate(candidate, train, None, dev, tmp_path / "out", seed=3, n_splits=3)
    result = tmp_path / "out" / "tfidf-lr"
    code = export_external_model.main(["--result", str(result), "--out", str(tmp_path / "m"), "--version", "t-v1",
                                       "--train-sha256", "a" * 64, "--dev-sha256", "b" * 64, "--legit-signal-rate", "0.5"])
    assert code == 0
    manifest = json.loads((tmp_path / "m" / "manifest.json").read_text(encoding="utf-8"))
    rows = list(csv.DictReader((result / "dev-scores.csv").open(encoding="utf-8")))
    expected = choose_threshold_at_rate([float(r["score"]) for r in rows], [int(r["label"]) for r in rows], 0.5)
    assert manifest["legit_signal_rate"] == 0.5 and manifest["threshold"] == expected
    assert "50%" in manifest["threshold_rule"] and "dev_crossfit_combined_at_rate_0" in manifest
    assert load_configured_model({MODEL_PATH_ENV: str(tmp_path / "m")}).status == "loaded"


def test_family_groups_sources():
    assert family("KR-MOB-SMISHING v1 ...") .startswith("KR-MOB")
    assert family("직접 작성") == "직접 작성"
    assert family("다른 출처") == "기타"


def test_run_candidate_writes_ids_and_scores_only(tmp_path):
    train = load_external(write_external(tmp_path / "train.csv"))
    dev = load_dev(write_csv(tmp_path / "eval.csv", binary_only=True))
    assert dev.test_rows_dropped > 0
    candidate = Candidate("tfidf-lr", "테스트", lambda seed: build_pipeline(DEFAULT_CONFIG, seed))
    result = run_candidate(candidate, train, None, dev, tmp_path / "out", seed=3, n_splits=3)
    scores = (tmp_path / "out" / "tfidf-lr" / "dev-scores.csv").read_text(encoding="utf-8")
    assert scores.splitlines()[0] == "id,label,score,fold,predicted"
    assert not any(t.format(i=0)[:6] in scores for t in FRAUD + NORMAL)
    assert result["combined"]["all"]["rows"] == len(dev.rows)
    with pytest.raises(TrainingError):
        run_candidate(candidate, train, None, dev, tmp_path / "out", seed=3, n_splits=3)


def test_rank_prefers_eligible_then_scam_warned():
    def result(name, warned, flagged, to_normal=0, seconds=1.0):
        return {"name": name, "train_seconds": seconds, "combined": {"all": {
            "scam_warned": warned, "legit_flagged": flagged, "scam_to_normal": to_normal, "errors": 0}, "families": {}}}
    rules = {"legit_flagged": 5}
    ranked = rank([result("많지만 오탐 늘어남", 90, 6), result("사기→정상", 95, 5, to_normal=1),
                   result("느림", 80, 5, seconds=9), result("빠름", 80, 4)], rules)
    assert [r["name"] for r in ranked][:2] == ["빠름", "느림"]


# -- 미세조정 모델 로더 --

class FakeSequenceClassifier:
    classes_ = [0, 1]
    seen: list = []

    def __init__(self, directory, tokenizer_kind, prefix, max_length):
        FakeSequenceClassifier.seen.append((tokenizer_kind, prefix, max_length))

    def predict_proba(self, texts):
        FakeSequenceClassifier.seen.append(tuple(texts))
        return [[0.2, 0.8] for _ in texts]


def write_transformer_dir(directory, **spec_changes):
    directory.mkdir(parents=True, exist_ok=True)
    weights, config = b"fake safetensors", b'{"model_type": "bert"}'
    (directory / "model.safetensors").write_bytes(weights)
    (directory / "config.json").write_bytes(config)
    spec = {"kind": "local-finetuned-sequence-classifier", "tokenizer": "auto", "prefix": "query: ", "max_length": 128,
            "config_sha256": hashlib.sha256(config).hexdigest()} | spec_changes
    manifest = {"format": MANIFEST_FORMAT, "model_version": "ft-test-v1", "model_file": "model.safetensors",
                "model_sha256": hashlib.sha256(weights).hexdigest(), "threshold": 0.7, "number_masking": True,
                "transformer": spec}
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return directory


def test_transformer_model_loads_and_masks_numbers(tmp_path, monkeypatch):
    monkeypatch.setattr(transformer_model, "SequenceClassifier", FakeSequenceClassifier)
    FakeSequenceClassifier.seen = []
    state = load_configured_model({MODEL_PATH_ENV: str(write_transformer_dir(tmp_path / "m"))})
    assert state.status == "loaded" and state.model.version == "ft-test-v1"
    assert state.model.score("문의 010-1234-5678") == pytest.approx(0.8)
    assert FakeSequenceClassifier.seen == [("auto", "query: ", 128), (f"문의 {PHONE_PLACEHOLDER}",)]


@pytest.mark.parametrize("change, reason", [
    ({"kind": "other"}, "MANIFEST_INVALID"),
    ({"tokenizer": "remote"}, "MANIFEST_INVALID"),
    ({"max_length": 0}, "MANIFEST_INVALID"),
    ({"config_sha256": "0" * 64}, "MODEL_SHA256_MISMATCH"),
])
def test_transformer_manifest_is_checked(tmp_path, monkeypatch, change, reason):
    monkeypatch.setattr(transformer_model, "SequenceClassifier", FakeSequenceClassifier)
    state = load_configured_model({MODEL_PATH_ENV: str(write_transformer_dir(tmp_path / "m", **change))})
    assert state.status == "load_failed" and state.reason == reason


def test_transformer_unavailable_is_a_fixed_code(tmp_path, monkeypatch):
    def broken(*args):
        raise transformer_model.TransformerUnavailable("x")
    monkeypatch.setattr(transformer_model, "SequenceClassifier", broken)
    state = load_configured_model({MODEL_PATH_ENV: str(write_transformer_dir(tmp_path / "m"))})
    assert state.status == "load_failed" and state.reason == "TRANSFORMER_UNAVAILABLE"


def test_number_masking_must_be_boolean(tmp_path, monkeypatch):
    monkeypatch.setattr(transformer_model, "SequenceClassifier", FakeSequenceClassifier)
    directory = write_transformer_dir(tmp_path / "m")
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    manifest["number_masking"] = "yes"
    (directory / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert load_configured_model({MODEL_PATH_ENV: str(directory)}).reason == "MANIFEST_INVALID"
