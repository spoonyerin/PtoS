"""KR-MOB-SMISHING v1 zip의 message_samples_used 본문을 라벨링 전용 평가 CSV로 바꾼다.

- zip을 풀지 않고 직접 읽는다. 경로 조작·이상한 이름·크기 초과 항목은 건너뛴다.
- 라벨링 파일에는 expected_level·split을 비워 두고 원래 case_type·incident_id를 넣지 않는다.
  id·campaign_id·행 순서는 고정 시드로 섞어 같은 입력이면 같은 결과가 나온다.
- id → case_type 매핑, 시드, 원본 zip의 SHA-256은 별도 매핑 폴더의 파일에만 기록한다.
- 출력은 저장소·OneDrive 밖에만 쓰고 기존 파일을 덮어쓰지 않는다.
- 로그와 오류에는 문자 본문을 넣지 않는다 (건수와 id만).

라벨링 파일은 평가에 바로 쓸 수 없다 (하네스가 빈 expected_level을 거부한다).
사람이 expected_level·split을 채우고 검수를 마친 파일만 evaluate.py --data로 쓴다 (docs/EVALUATION.md).
"""
import argparse
import csv
import hashlib
import json
import os
import random
import re
import sys
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

REPO_ROOT = Path(__file__).resolve().parents[1]

# backend/evaluation/harness.py의 REQUIRED_COLUMNS와 같아야 한다 (테스트로 확인).
EVAL_COLUMNS = (
    "id", "text", "url", "expected_level", "label_reason", "source",
    "is_synthetic", "campaign_id", "split", "review_status",
)
LABELING_COLUMNS = EVAL_COLUMNS + ("watermark_removed",)
MAPPING_COLUMNS = ("id", "campaign_id", "incident_id", "case_type", "seed", "source_zip_sha256")

LABELING_NAME = "kr-mob-smishing-v1.labeling.csv"
MAPPING_NAME = "kr-mob-smishing-v1.case_type_mapping.csv"
SOURCE = (
    "KR-MOB-SMISHING v1 (KR-MOB-SMISHING Project, 2026), CC BY-NC 4.0 "
    "https://creativecommons.org/licenses/by-nc/4.0/ ; 비상업 이용. "
    "변경: incident JSON의 message_samples_used.text만 추출, 맨 앞 [TRAINING] 워터마크와 바로 뒤 공백 1칸 제거, "
    "다른 메타데이터 제외"
)
WATERMARK = "[TRAINING]"
CASE_TYPES = ("malicious", "benign_lookalike", "benign")

DEFAULT_SEED = 20261027
EXPECTED_ROWS = 104
EXPECTED_CAMPAIGNS = 100
MAX_ENTRIES = 2_000
MAX_ENTRY_BYTES = 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024

FILE_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\.json")
INCIDENT_ID = re.compile(r"inc-[A-Za-z0-9-]{1,64}")


class ConversionError(Exception):
    """변환 실패. 메시지에 본문을 넣지 않는다."""


@dataclass(frozen=True)
class Incident:
    incident_id: str
    case_type: str
    texts: tuple[str, ...]


@dataclass
class ReadStats:
    accepted: int = 0
    unsafe_names: int = 0
    duplicate_names: int = 0
    oversized: int = 0
    other_files: int = 0


def _is_safe_name(name: str) -> bool:
    if not name or not name.isprintable() or "\\" in name or ":" in name or name.startswith("/"):
        return False
    parts = PurePosixPath(name).parts
    return all(part not in ("", ".", "..") for part in parts)


def read_incidents(zip_path: Path, max_entry_bytes=MAX_ENTRY_BYTES, max_total_bytes=MAX_TOTAL_BYTES):
    """zip 안의 <root>/incidents/*.json만 읽는다. 안전하지 않은 항목은 건너뛰고 개수만 센다."""
    stats = ReadStats()
    incidents: dict[str, Incident] = {}
    total = 0
    with zipfile.ZipFile(zip_path) as archive:
        infos = archive.infolist()
        if len(infos) > MAX_ENTRIES:
            raise ConversionError(f"zip 항목이 너무 많아요 ({len(infos)}개 > {MAX_ENTRIES}개).")
        counts: dict[str, int] = {}
        for info in infos:
            counts[info.filename] = counts.get(info.filename, 0) + 1
        for info in sorted(infos, key=lambda item: item.filename):
            name = info.filename
            if info.is_dir():
                continue
            if not _is_safe_name(name):
                stats.unsafe_names += 1
                continue
            if counts[name] > 1:
                stats.duplicate_names += 1
                continue
            parts = PurePosixPath(name).parts
            if len(parts) != 3 or parts[1] != "incidents":
                stats.other_files += 1
                continue
            if not FILE_NAME.fullmatch(parts[2]):
                stats.unsafe_names += 1
                continue
            if info.file_size > max_entry_bytes:
                stats.oversized += 1
                continue
            # 헤더의 크기를 믿지 않고 실제로 읽은 바이트로 다시 제한한다.
            with archive.open(info) as handle:
                data = handle.read(max_entry_bytes + 1)
            if len(data) > max_entry_bytes:
                stats.oversized += 1
                continue
            total += len(data)
            if total > max_total_bytes:
                raise ConversionError(f"전체 압축 해제 크기가 상한({max_total_bytes} bytes)을 넘었어요.")
            incident = _parse_incident(data, parts[2])
            if incident.incident_id in incidents:
                raise ConversionError(f"incident_id가 중복돼요: {incident.incident_id}")
            incidents[incident.incident_id] = incident
            stats.accepted += 1
    return [incidents[key] for key in sorted(incidents)], stats


def _parse_incident(data: bytes, file_name: str) -> Incident:
    try:
        record = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ConversionError(f"{file_name}: JSON을 읽지 못했어요.") from None
    if not isinstance(record, dict):
        raise ConversionError(f"{file_name}: 최상위가 객체가 아니에요.")
    incident_id = record.get("incident_id")
    if not isinstance(incident_id, str) or not INCIDENT_ID.fullmatch(incident_id):
        raise ConversionError(f"{file_name}: incident_id 형식이 맞지 않아요.")
    case_type = record.get("case_type")
    if case_type not in CASE_TYPES:
        raise ConversionError(f"{incident_id}: case_type이 {'/'.join(CASE_TYPES)} 중 하나가 아니에요.")
    samples = record.get("message_samples_used")
    if not isinstance(samples, list) or not samples:
        raise ConversionError(f"{incident_id}: message_samples_used가 비어 있어요.")
    texts = []
    for index, sample in enumerate(samples):
        text = sample.get("text") if isinstance(sample, dict) else None
        if not isinstance(text, str):
            raise ConversionError(f"{incident_id}: message_samples_used[{index}].text가 문자열이 아니에요.")
        texts.append(text)
    return Incident(incident_id, case_type, tuple(texts))


def strip_watermark(text: str) -> tuple[str, bool]:
    """맨 앞의 [TRAINING]과 바로 뒤 공백 1칸만 제거한다. 다른 곳은 건드리지 않는다."""
    if not text.startswith(WATERMARK):
        return text, False
    rest = text[len(WATERMARK):]
    return (rest[1:] if rest.startswith(" ") else rest), True


def build_rows(incidents, seed: int, zip_sha256: str):
    rng = random.Random(seed)
    order = list(incidents)
    rng.shuffle(order)
    campaigns = {incident.incident_id: f"C-{index:03d}" for index, incident in enumerate(order, start=1)}
    samples = [(incident, text) for incident in incidents for text in incident.texts]
    rng.shuffle(samples)
    labeling, mapping = [], []
    for index, (incident, raw) in enumerate(samples, start=1):
        row_id = f"KMS-{index:03d}"
        text, removed = strip_watermark(raw)
        campaign = campaigns[incident.incident_id]
        labeling.append({
            "id": row_id, "text": text, "url": "", "expected_level": "", "label_reason": "",
            "source": SOURCE, "is_synthetic": "true", "campaign_id": campaign, "split": "",
            "review_status": "", "watermark_removed": "true" if removed else "false",
        })
        mapping.append({
            "id": row_id, "campaign_id": campaign, "incident_id": incident.incident_id,
            "case_type": incident.case_type, "seed": str(seed), "source_zip_sha256": zip_sha256,
        })
    return labeling, mapping


def verify(labeling, expected_rows=EXPECTED_ROWS, expected_campaigns=EXPECTED_CAMPAIGNS) -> dict:
    """건수·빈 본문·중복·id 유일성·campaign 수·워터마크 제거를 확인한다. 본문은 반환하지 않는다."""
    texts = [row["text"] for row in labeling]
    normalized = [" ".join(text.split()) for text in texts]
    ids = [row["id"] for row in labeling]
    summary = {
        "rows": len(labeling),
        "empty_text": sum(1 for text in normalized if not text),
        "duplicate_text": len(normalized) - len(set(normalized)),
        "duplicate_id": len(ids) - len(set(ids)),
        "campaigns": len({row["campaign_id"] for row in labeling}),
        "watermark_removed": sum(1 for row in labeling if row["watermark_removed"] == "true"),
        "watermark_left_at_start": sum(1 for text in texts if text.lstrip().startswith(WATERMARK)),
    }
    problems = []
    if summary["rows"] != expected_rows:
        problems.append(f"행 수 {summary['rows']} (기대 {expected_rows})")
    if summary["empty_text"]:
        problems.append(f"빈 본문 {summary['empty_text']}건")
    if summary["duplicate_text"]:
        problems.append(f"중복 본문 {summary['duplicate_text']}건")
    if summary["duplicate_id"]:
        problems.append(f"중복 id {summary['duplicate_id']}건")
    if summary["campaigns"] != expected_campaigns:
        problems.append(f"campaign_id {summary['campaigns']}개 (기대 {expected_campaigns})")
    if summary["watermark_removed"] != summary["rows"] or summary["watermark_left_at_start"]:
        problems.append(f"워터마크 제거 {summary['watermark_removed']}/{summary['rows']}건")
    if problems:
        raise ConversionError("검증 실패: " + ", ".join(problems))
    return summary


def _synced_roots() -> list[Path]:
    roots = [os.environ.get(name) for name in ("OneDrive", "OneDriveConsumer", "OneDriveCommercial")]
    return [Path(root).resolve() for root in roots if root]


def check_output_dir(directory: Path) -> Path:
    resolved = directory.resolve()
    forbidden = [REPO_ROOT, *_synced_roots()]
    # 환경 변수가 없어도 OneDrive 기본 폴더 이름("OneDrive", "OneDrive - 조직")은 막는다.
    if any(resolved == root or root in resolved.parents for root in forbidden) or any(
        part.lower() == "onedrive" or part.lower().startswith("onedrive - ") for part in resolved.parts
    ):
        raise ConversionError("출력 폴더가 저장소나 OneDrive 안에 있어요. 동기화되지 않는 저장소 밖 폴더를 지정해주세요.")
    return resolved


def _write_csv(path: Path, columns, rows) -> None:
    # Excel에서 열 수 있도록 UTF-8 BOM으로 쓴다. 하네스는 BOM 유무를 모두 읽는다.
    with path.open("x", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        writer.writerows(rows)


def convert(zip_path: Path, out_dir: Path, mapping_dir: Path, seed: int = DEFAULT_SEED,
            expected_rows=EXPECTED_ROWS, expected_campaigns=EXPECTED_CAMPAIGNS,
            max_entry_bytes=MAX_ENTRY_BYTES, max_total_bytes=MAX_TOTAL_BYTES) -> dict:
    out_dir, mapping_dir = check_output_dir(out_dir), check_output_dir(mapping_dir)
    if out_dir == mapping_dir:
        raise ConversionError("매핑 파일은 라벨링 파일과 다른 폴더에 써야 해요.")
    labeling_path, mapping_path = out_dir / LABELING_NAME, mapping_dir / MAPPING_NAME
    existing = [path.name for path in (labeling_path, mapping_path) if path.exists()]
    if existing:
        raise ConversionError(f"이미 있는 파일은 덮어쓰지 않아요: {', '.join(existing)}")

    zip_sha256 = hashlib.sha256(zip_path.read_bytes()).hexdigest()
    incidents, stats = read_incidents(zip_path, max_entry_bytes, max_total_bytes)
    labeling, mapping = build_rows(incidents, seed, zip_sha256)
    summary = verify(labeling, expected_rows, expected_campaigns)

    out_dir.mkdir(parents=True, exist_ok=True)
    mapping_dir.mkdir(parents=True, exist_ok=True)
    _write_csv(labeling_path, LABELING_COLUMNS, labeling)
    try:
        _write_csv(mapping_path, MAPPING_COLUMNS, mapping)
    except BaseException:
        labeling_path.unlink(missing_ok=True)
        raise
    return {
        **summary, "incidents": len(incidents), "stats": stats,
        "first_id": labeling[0]["id"], "last_id": labeling[-1]["id"],
        "labeling_path": labeling_path, "mapping_path": mapping_path,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="KR-MOB-SMISHING v1 → 라벨링 전용 평가 CSV (본문은 출력하지 않음)")
    parser.add_argument("--zip", required=True, type=Path, help="원본 zip 경로")
    parser.add_argument("--out-dir", required=True, type=Path, help="라벨링 파일 폴더 (저장소·OneDrive 밖)")
    parser.add_argument("--mapping-dir", type=Path, help="매핑 파일 폴더 (기본: <out-dir>/mapping)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED, help=f"섞기 시드 (기본 {DEFAULT_SEED})")
    args = parser.parse_args(argv)
    try:
        result = convert(args.zip, args.out_dir, args.mapping_dir or args.out_dir / "mapping", args.seed,
                         EXPECTED_ROWS, EXPECTED_CAMPAIGNS)
    except (ConversionError, OSError, zipfile.BadZipFile) as error:
        message = str(error) if isinstance(error, ConversionError) else type(error).__name__
        print(f"변환하지 않았어요: {message}", file=sys.stderr)
        return 1
    stats = result["stats"]
    print(f"incident {result['incidents']}개, 본문 {result['rows']}건 → id {result['first_id']}~{result['last_id']}")
    print(f"건너뛴 zip 항목: 이상한 이름·경로 {stats.unsafe_names}, 중복 이름 {stats.duplicate_names}, "
          f"크기 초과 {stats.oversized}, incidents 밖 파일 {stats.other_files}")
    print(f"검증: 행 {result['rows']}, 빈 본문 {result['empty_text']}, 중복 본문 {result['duplicate_text']}, "
          f"중복 id {result['duplicate_id']}, campaign_id {result['campaigns']}개, "
          f"워터마크 제거 {result['watermark_removed']}/{result['rows']}")
    print(f"라벨링 전용 파일: {result['labeling_path']}")
    print(f"매핑 파일(라벨링 중 열지 않음): {result['mapping_path']}")
    print("이 파일은 expected_level·split이 비어 있어 평가에 쓸 수 없어요. 라벨링·검수를 마친 파일만 evaluate.py --data로 쓰세요.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
