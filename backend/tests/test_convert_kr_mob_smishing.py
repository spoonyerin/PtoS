"""KR-MOB-SMISHING 변환 스크립트의 코드 동작 검증. zip은 가짜 합성 문장만 담아 테스트 안에서 만든다."""
import csv
import hashlib
import importlib.util
import json
import zipfile
from pathlib import Path

import pytest

from evaluation.harness import REQUIRED_COLUMNS, DatasetError, load_rows

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "convert_kr_mob_smishing.py"
spec = importlib.util.spec_from_file_location("convert_kr_mob_smishing_under_test", SCRIPT)
convert_mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(convert_mod)

FAKE = "[가짜 테스트 샘플]"
ROOT = "KR-MOB-SMISHING-100-v1"


def raw_incident(incident_id, case_type, raw_texts):
    body = {
        "incident_id": incident_id, "case_type": case_type,
        "message_samples_used": [{"text": text, "sender_type": "verified_sender"} for text in raw_texts],
    }
    return f"{ROOT}/incidents/{incident_id}.json", json.dumps(body, ensure_ascii=False).encode()


def incident(incident_id, case_type, *texts):
    return raw_incident(incident_id, case_type, [f"[TRAINING] {FAKE} {text}" for text in texts])


INCIDENTS = [
    incident("inc-MOB-MAL-001", "malicious", "본문A 비밀원문"),
    incident("inc-MOB-BEN-002", "benign_lookalike", "본문B", "본문C"),
    incident("inc-MOB-BEN-003", "benign", "본문D"),
]


def make_zip(path, entries=INCIDENTS, extra=()):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(f"{ROOT}/README.md", "readme")
        for name, data in [*entries, *extra]:
            # ZipInfo 생성자의 이름 정리를 거치지 않도록 이름을 직접 넣는다.
            info = zipfile.ZipInfo("placeholder")
            info.filename = name
            archive.writestr(info, data)
    return path


def run(tmp_path, zip_path, **kwargs):
    kwargs.setdefault("expected_rows", 4)
    kwargs.setdefault("expected_campaigns", 3)
    return convert_mod.convert(zip_path, tmp_path / "out", tmp_path / "out" / "mapping", **kwargs)


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def test_columns_match_harness():
    assert convert_mod.EVAL_COLUMNS == REQUIRED_COLUMNS


def test_labeling_file_hides_labels_and_strips_only_leading_watermark(tmp_path):
    result = run(tmp_path, make_zip(tmp_path / "src.zip"))
    labeling_bytes = result["labeling_path"].read_bytes()
    assert labeling_bytes.startswith(b"\xef\xbb\xbf")
    rows = read_csv(result["labeling_path"])
    assert [row["id"] for row in rows] == ["KMS-001", "KMS-002", "KMS-003", "KMS-004"]
    assert list(rows[0]) == list(convert_mod.LABELING_COLUMNS)
    for row in rows:
        assert row["text"].startswith(FAKE) and "[TRAINING]" not in row["text"]
        assert row["expected_level"] == row["split"] == row["url"] == row["review_status"] == ""
        assert row["is_synthetic"] == "true" and row["watermark_removed"] == "true"
        assert "CC BY-NC 4.0" in row["source"] and "[TRAINING]" in row["source"]
    text = labeling_bytes.decode("utf-8-sig")
    for leaked in ("inc-MOB", "MAL", "BEN", "malicious", "benign", "verified_sender", "sha256",
                   str(convert_mod.DEFAULT_SEED)):
        assert leaked not in text
    assert result["mapping_path"].parent.name == "mapping"


def test_mapping_groups_incident_campaign_and_records_seed_and_hash(tmp_path):
    zip_path = make_zip(tmp_path / "src.zip")
    result = run(tmp_path, zip_path, seed=7)
    labeling = {row["id"]: row for row in read_csv(result["labeling_path"])}
    mapping = read_csv(result["mapping_path"])
    assert {row["incident_id"]: row["case_type"] for row in mapping} == {
        "inc-MOB-MAL-001": "malicious", "inc-MOB-BEN-002": "benign_lookalike", "inc-MOB-BEN-003": "benign",
    }
    campaigns = {}
    for row in mapping:
        assert labeling[row["id"]]["campaign_id"] == row["campaign_id"]
        campaigns.setdefault(row["incident_id"], set()).add(row["campaign_id"])
    assert all(len(values) == 1 for values in campaigns.values())
    assert len({next(iter(values)) for values in campaigns.values()}) == 3
    assert {row["seed"] for row in mapping} == {"7"}
    assert {row["source_zip_sha256"] for row in mapping} == {hashlib.sha256(zip_path.read_bytes()).hexdigest()}


def test_same_seed_same_output_different_seed_differs(tmp_path):
    zip_path = make_zip(tmp_path / "src.zip")
    outputs = []
    for name, seed in (("a", 1), ("b", 1), ("c", 2)):
        result = convert_mod.convert(zip_path, tmp_path / name, tmp_path / name / "mapping", seed,
                                     expected_rows=4, expected_campaigns=3)
        outputs.append((result["labeling_path"].read_bytes(), result["mapping_path"].read_bytes()))
    assert outputs[0] == outputs[1]
    assert outputs[0][1] != outputs[2][1]


def test_unsafe_and_oversized_entries_are_ignored(tmp_path):
    payload = incident("inc-MOB-MAL-009", "malicious", "끼어든 본문")[1]
    extra = [
        (f"{ROOT}/incidents/../inc-MOB-MAL-009.json", payload),
        ("../inc-MOB-MAL-009.json", payload),
        ("/abs/incidents/inc-MOB-MAL-009.json", payload),
        (f"{ROOT}/incidents/inc-MOB-\x08-009.json", payload),
        (f"{ROOT}/incidents/inc MOB 009.json", payload),
        (f"{ROOT}/incidents/dup.json", payload),
        (f"{ROOT}/incidents/dup.json", payload),
        (f"{ROOT}/incidents/big.json", b" " * 2048),
        (f"{ROOT}/other/inc-MOB-MAL-009.json", payload),
    ]
    with pytest.warns(UserWarning, match="Duplicate name"):
        zip_path = make_zip(tmp_path / "src.zip", extra=extra)
    result = run(tmp_path, zip_path, max_entry_bytes=1024)
    stats = result["stats"]
    assert result["incidents"] == 3 and result["rows"] == 4
    assert stats.unsafe_names == 5 and stats.duplicate_names == 2
    assert stats.oversized == 1 and stats.other_files == 2


def test_total_uncompressed_limit_stops_conversion(tmp_path):
    with pytest.raises(convert_mod.ConversionError, match="전체 압축 해제 크기"):
        run(tmp_path, make_zip(tmp_path / "src.zip"), max_total_bytes=300)
    assert not (tmp_path / "out").exists()


@pytest.mark.parametrize("entries, message", [
    ([incident("inc-MOB-MAL-001", "malicious", "같은 본문"), incident("inc-MOB-BEN-002", "benign", "같은 본문")], "중복 본문"),
    ([raw_incident("inc-MOB-MAL-001", "malicious", ["[TRAINING]   "])], "빈 본문"),
], ids=["duplicate", "empty"])
def test_verification_failure_writes_nothing_and_hides_text(tmp_path, entries, message):
    with pytest.raises(convert_mod.ConversionError) as error:
        run(tmp_path, make_zip(tmp_path / "src.zip", entries=entries),
            expected_rows=len(entries), expected_campaigns=len(entries))
    assert message in str(error.value) and "같은 본문" not in str(error.value)
    assert not (tmp_path / "out").exists()


def test_watermark_only_removed_at_start():
    assert convert_mod.strip_watermark("[TRAINING] 본문 [TRAINING]") == ("본문 [TRAINING]", True)
    assert convert_mod.strip_watermark("본문 [TRAINING]") == ("본문 [TRAINING]", False)


def test_refuses_repo_onedrive_same_dir_and_overwrite(tmp_path, monkeypatch):
    zip_path = make_zip(tmp_path / "src.zip")
    with pytest.raises(convert_mod.ConversionError, match="저장소나 OneDrive"):
        convert_mod.convert(zip_path, convert_mod.REPO_ROOT / "eval-data", tmp_path / "m")
    monkeypatch.setenv("OneDrive", str(tmp_path / "synced"))
    with pytest.raises(convert_mod.ConversionError, match="저장소나 OneDrive"):
        convert_mod.convert(zip_path, tmp_path / "synced" / "eval", tmp_path / "m")
    with pytest.raises(convert_mod.ConversionError, match="저장소나 OneDrive"):
        convert_mod.convert(zip_path, tmp_path / "OneDrive - Org" / "eval", tmp_path / "m")
    with pytest.raises(convert_mod.ConversionError, match="다른 폴더"):
        convert_mod.convert(zip_path, tmp_path / "x", tmp_path / "x")
    run(tmp_path, zip_path)
    with pytest.raises(convert_mod.ConversionError, match="덮어쓰지"):
        run(tmp_path, zip_path)


def test_cli_prints_counts_and_ids_only(tmp_path, capsys, monkeypatch):
    monkeypatch.setattr(convert_mod, "EXPECTED_ROWS", 4)
    monkeypatch.setattr(convert_mod, "EXPECTED_CAMPAIGNS", 3)
    zip_path = make_zip(tmp_path / "src.zip")
    assert convert_mod.main(["--zip", str(zip_path), "--out-dir", str(tmp_path / "out")]) == 0
    assert (tmp_path / "out" / "mapping" / convert_mod.MAPPING_NAME).exists()
    assert convert_mod.main(["--zip", str(zip_path), "--out-dir", str(tmp_path / "out")]) == 1
    out = capsys.readouterr()
    assert "KMS-001~KMS-004" in out.out and "라벨링 전용" in out.out
    for leaked in (FAKE, "본문A", "비밀원문", "inc-MOB", "malicious"):
        assert leaked not in out.out + out.err


def test_harness_rejects_labeling_file_until_labels_are_filled(tmp_path):
    result = run(tmp_path, make_zip(tmp_path / "src.zip"))
    with pytest.raises(DatasetError, match="expected_level"):
        load_rows(result["labeling_path"])
    rows = read_csv(result["labeling_path"])
    for row in rows:
        row.update(expected_level="suspicious", split="dev")
    labeled = tmp_path / "labeled.csv"
    with labeled.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(convert_mod.LABELING_COLUMNS))
        writer.writeheader()
        writer.writerows(rows)
    loaded = load_rows(labeled)
    assert [r.id for r in loaded] == [row["id"] for row in rows]
    assert len({r.campaign_id for r in loaded}) == 3
