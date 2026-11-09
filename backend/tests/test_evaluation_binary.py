"""이진 평가 모드의 코드 동작 검증. 모든 샘플은 명백한 가짜 합성 문장이며 결과는 탐지 성능이 아니다."""

import subprocess
import sys

import pytest

from evaluation import model_training
from evaluation.harness import (
    BINARY_COLUMN, REQUIRED_COLUMNS, DatasetError, EvalRow, Outcome, binary_label, compute_binary_metrics, load_rows,
    render_binary_report, run,
)
from test_evaluation import BACKEND, FAKE, SAMPLE, SECRET, ScriptedAnalyzer, fake_row, info, write_csv

BINARY_COLUMNS = (*REQUIRED_COLUMNS, BINARY_COLUMN)


def brow(row_id, expected_level, expected_binary="", **kwargs):
    return {**fake_row(row_id, expected_level, **kwargs), BINARY_COLUMN: expected_binary}


def erow(row_id, expected, binary=None, input_type="text", split="dev", synthetic=True):
    return EvalRow(row_id, input_type, "x", expected, split, synthetic, "", "agreed", binary)


def out(row_id, expected, predicted, binary=None, **kwargs):
    return Outcome(erow(row_id, expected, binary, **kwargs), predicted)


def scripted():
    return {"scripted": ScriptedAnalyzer}


# ---- CSV 읽기 ----

def test_binary_column_is_optional_and_old_csv_reads_the_same(tmp_path):
    old = load_rows(write_csv(tmp_path / "old.csv", SAMPLE))
    assert all(r.expected_binary is None for r in old)
    blank = load_rows(write_csv(tmp_path / "new.csv", [{**s, BINARY_COLUMN: ""} for s in SAMPLE], BINARY_COLUMNS))
    assert blank == old


def test_load_rows_accepts_binary_only_and_both(tmp_path):
    rows = load_rows(write_csv(tmp_path / "b.csv", [
        brow("FAKE-1", "", "scam", text=f"{FAKE} 가"),
        brow("FAKE-2", "", "legit", text=f"{FAKE} 나"),
        brow("FAKE-3", "dangerous", "scam", text=f"{FAKE} 다"),
        brow("FAKE-4", "insufficient_information", "legit", text=f"{FAKE} 라"),
    ], BINARY_COLUMNS))
    assert [(r.expected, r.expected_binary) for r in rows] == [
        (None, "scam"), (None, "legit"), ("dangerous", "scam"), ("insufficient_information", "legit")]


@pytest.mark.parametrize("level, binary, message", [
    ("", "", "모두 비어"),
    ("dangerous", "legit", "서로 맞지"),
    ("suspicious", "legit", "서로 맞지"),
    ("normal", "scam", "서로 맞지"),
    ("", SECRET, "expected_binary는"),
    (SECRET, "scam", "expected_level"),
], ids=["both-empty", "dangerous-legit", "suspicious-legit", "normal-scam", "bad-binary", "bad-level"])
def test_load_rows_rejects_invalid_binary_without_echoing_cells(tmp_path, level, binary, message):
    with pytest.raises(DatasetError) as error:
        load_rows(write_csv(tmp_path / "bad.csv", [brow("FAKE-1", level, binary, text=SECRET)], BINARY_COLUMNS))
    assert message in str(error.value)
    assert "비밀원문" not in str(error.value)


def test_empty_level_without_binary_column_keeps_old_error(tmp_path):
    with pytest.raises(DatasetError, match="expected_level은"):
        load_rows(write_csv(tmp_path / "bad.csv", [fake_row("FAKE-1", "", text=SECRET)]))


# ---- 라벨 만들기 ----

@pytest.mark.parametrize("expected, binary, label", [
    ("dangerous", None, ("scam", "from_dangerous")),
    ("suspicious", None, ("scam", "from_suspicious")),
    ("normal", None, ("legit", "from_normal")),
    ("insufficient_information", None, (None, None)),
    ("insufficient_information", "scam", ("scam", "direct")),
    (None, "legit", ("legit", "direct")),
    ("dangerous", "scam", ("scam", "direct")),
])
def test_binary_label_and_source(expected, binary, label):
    assert binary_label(erow("FAKE", expected, binary)) == label


# ---- 지표 ----

def test_binary_metrics_counts_misses_false_alarms_and_errors_separately():
    outcomes = [
        out("S1", "dangerous", "dangerous"),
        out("S2", "dangerous", "suspicious"),
        out("S3", "suspicious", "insufficient_information"),
        out("S4", "suspicious", "normal"),
        out("S5", None, "timeout", "scam"),
        out("L1", "normal", "insufficient_information"),
        out("L2", "normal", "suspicious"),
        out("L3", None, "dangerous", "legit"),
        out("L4", "normal", "input_error"),
    ]
    m = compute_binary_metrics(outcomes)
    assert m.confusion["scam"] == {
        "normal": 1, "insufficient_information": 1, "suspicious": 1, "dangerous": 1,
        "input_error": 0, "timeout": 1, "analysis_error": 0,
    }
    assert (m.scam_total, m.scam_warned, m.scam_missed, m.scam_errors, m.scam_dangerous) == (5, 2, 2, 1, 1)
    assert (m.legit_total, m.legit_flagged, m.legit_dangerous, m.legit_errors) == (4, 2, 1, 1)
    assert (m.total, m.insufficient_predicted, m.errors) == (9, 2, 2)


def test_binary_metrics_rejects_unlabeled_rows():
    with pytest.raises(ValueError):
        compute_binary_metrics([out("I1", "insufficient_information", "suspicious")])


# ---- 리포트 ----

def section(report, start, end=None):
    begin = report.index(start)
    return report[begin:report.index(end, begin)] if end else report[begin:]


def test_binary_report_rates_with_denominators_and_lists():
    outcomes = [
        out("S1", "dangerous", "dangerous"),
        out("S2", "suspicious", "insufficient_information"),
        out("S3", None, "timeout", "scam"),
        out("L1", "normal", "insufficient_information"),
        out("L2", "normal", "dangerous", synthetic=False),
        out("I1", "insufficient_information", "suspicious"),
    ]
    report = render_binary_report(outcomes, info())
    assert "| 평가 모드 | binary" in report
    assert "이진 지표에서 제외: 1건" in report
    dev = section(report, "## split: dev")
    assert "판정 분포: suspicious 1" in dev
    whole = section(dev, "#### 전체 (5건)", "#### text 입력")
    assert "| scam | 0 | 1 | 0 | 1 | 0 | 1 | 0 | 3 |" in whole
    assert "| legit | 0 | 1 | 0 | 1 | 0 | 0 | 0 | 2 |" in whole
    assert "사기 경고율 (scam 중 의심·위험): 1/3 = 0.333 (분모에 오류 1건 포함)" in whole
    assert "사기 놓침 (scam 중 정보 부족·정상): 1건" in whole
    assert "정상 오탐률 (legit 중 의심·위험): 1/2 = 0.500 (분모에 오류 0건 포함)" in whole
    assert "정상 → 위험 (심각한 오탐): 1건" in whole
    assert "사기 중 위험 판정 비율: 1/3 = 0.333" in whole
    assert "정보 부족 판정 비율: 2/5 = 0.400" in whole
    assert "경고 없음으로 합치지 않음): 1건" in whole
    assert "#### url 입력 (0건)" in dev
    missed = section(dev, "#### 놓친 사기 id (scam → 경고 없음) (1건)", "#### 정상 오탐 id")
    assert "| S2 | text | suspicious에서 파생 | insufficient_information |" in missed
    assert "S3" not in missed  # 오류는 놓침이 아니다.
    assert "| L2 | text | normal에서 파생 | dangerous |" in section(dev, "#### 정상 오탐 id (legit → 의심·위험) (1건)", "#### 오류 id")
    assert "| S3 | text | 직접 채운 expected_binary | timeout |" in section(dev, "#### 오류 id (1건)")


def test_binary_summary_has_overall_real_synthetic_then_source_rows():
    outcomes = [
        out("D1", "dangerous", "dangerous"),
        out("D2", "dangerous", "insufficient_information", synthetic=False),
        out("S1", "suspicious", "suspicious"),
        out("S2", "suspicious", "insufficient_information"),
        out("S3", "suspicious", "normal"),
        out("B1", None, "suspicious", "scam"),
        out("B2", "insufficient_information", "insufficient_information", "legit"),
        out("N1", "normal", "suspicious", synthetic=False),
    ]
    summary = section(render_binary_report(outcomes, info()), "#### 구분별 지표", "#### 놓친 사기 id")
    rows = [line for line in summary.splitlines() if line.startswith("| ") and not line.startswith("| 구분") and "---" not in line]
    assert [line.split(" | ")[0][2:] for line in rows] == [
        "전체", "실제", "합성", "출처: 직접 채운 expected_binary", "출처: dangerous에서 파생",
        "출처: suspicious에서 파생", "출처: normal에서 파생",
    ]
    assert rows[0] == "| 전체 | 8 | 3/6 = 0.500 | 1/2 = 0.500 | 0 | 1/6 = 0.167 | 3/8 = 0.375 | 0 |"
    assert rows[1] == "| 실제 | 2 | 0/1 = 0.000 | 1/1 = 1.000 | 0 | 0/1 = 0.000 | 1/2 = 0.500 | 0 |"
    assert rows[3] == "| 출처: 직접 채운 expected_binary | 2 | 1/1 = 1.000 | 0/1 = 0.000 | 0 | 0/1 = 0.000 | 1/2 = 0.500 | 0 |"
    assert rows[4] == "| 출처: dangerous에서 파생 | 2 | 1/2 = 0.500 | 0/0 = N/A | 0 | 1/2 = 0.500 | 1/2 = 0.500 | 0 |"
    assert rows[5] == "| 출처: suspicious에서 파생 | 3 | 1/3 = 0.333 | 0/0 = N/A | 0 | 0/3 = 0.000 | 1/3 = 0.333 | 0 |"
    assert rows[6] == "| 출처: normal에서 파생 | 1 | 0/0 = N/A | 1/1 = 1.000 | 0 | 0/0 = N/A | 0/1 = 0.000 | 0 |"
    assert "suspicious에서 파생한 scam은 정답이 불확실하다" in summary
    assert "이진 라벨 출처: 직접 채운 expected_binary 2, dangerous에서 파생 2, suspicious에서 파생 3, normal에서 파생 1" \
        in render_binary_report(outcomes, info())


def test_binary_source_rows_sum_to_overall_counts():
    outcomes = [out(f"R{i}", level, "suspicious") for i, level in enumerate(["dangerous", "suspicious", "normal"])]
    outcomes.append(out("R9", None, "insufficient_information", "scam"))
    summary = section(render_binary_report(outcomes, info()), "#### 구분별 지표", "#### 놓친 사기 id")
    counts = {line.split(" | ")[0][2:]: int(line.split(" | ")[1]) for line in summary.splitlines()
              if line.startswith("| ") and "---" not in line and not line.startswith("| 구분")}
    assert counts["전체"] == sum(v for k, v in counts.items() if k.startswith("출처: ")) == 4


# ---- run, CLI ----

MIXED = [
    brow("FAKE-B1", "", "scam", text=f"{FAKE} <dangerous>"),
    brow("FAKE-B2", "", "legit", text=f"{FAKE} <insufficient_information>"),
    brow("FAKE-L1", "suspicious", text=f"{FAKE} <suspicious>"),
    brow("FAKE-L2", "normal", text=f"{FAKE} <suspicious>", synthetic="false"),
    brow("FAKE-I1", "insufficient_information", text=f"{FAKE} <insufficient_information>", campaign="FAKE-C7"),
    brow("FAKE-T1", "dangerous", split="test", text=f"{FAKE} <dangerous>", campaign="FAKE-C7"),
]


def test_run_binary_mode_without_raw_text_or_campaign(tmp_path):
    path = write_csv(tmp_path / "mixed.csv", MIXED, BINARY_COLUMNS)
    report = run(path, "scripted", analyzers=scripted(), mode="binary")
    assert "## split: dev" in report and "## split: test" in report
    assert "평가 행: 6건 (실제 1건, 합성 5건)" in report
    assert "campaign_id 1개가 dev와 test에 함께" in report
    for sample in MIXED:
        for column in ("text", "url", "label_reason"):
            if sample[column]:
                assert sample[column] not in report
    assert FAKE not in report and "FAKE-C7" not in report


def test_run_levels_mode_excludes_binary_only_rows_with_count(tmp_path):
    seen = []

    class Recording(ScriptedAnalyzer):
        async def analyze(self, data):
            seen.append(data.content)
            return await super().analyze(data)

    path = write_csv(tmp_path / "mixed.csv", MIXED, BINARY_COLUMNS)
    report = run(path, "recording", analyzers={"recording": Recording})
    assert len(seen) == 4  # 이진 라벨만 있는 2행은 분석기에 넘기지 않는다.
    assert "평가 행: 4건" in report and "4단계 라벨(expected_level) 없음으로 제외: 2건" in report
    assert "FAKE-B1" not in report and "평가 모드" not in report


def test_run_levels_report_has_no_exclusion_line_for_old_csv(tmp_path):
    report = run(write_csv(tmp_path / "old.csv", SAMPLE), "scripted", analyzers=scripted())
    assert "4단계 라벨" not in report and "평가 모드" not in report


def test_run_binary_split_filter_and_test_note(tmp_path):
    seen = []

    class Recording(ScriptedAnalyzer):
        async def analyze(self, data):
            seen.append(data.content)
            return await super().analyze(data)

    path = write_csv(tmp_path / "mixed.csv", MIXED, BINARY_COLUMNS)
    report = run(path, "recording", analyzers={"recording": Recording}, split="dev", mode="binary")
    assert len(seen) == 5 and "## split: test" not in report and "split 필터로 제외: 1건" in report
    report = run(path, "recording", analyzers={"recording": Recording}, split="test", mode="binary")
    assert "## split: dev" not in report and "최종 테스트셋은 정책·임계값 조정에 쓰지 않는다." in report


def test_run_old_four_level_csv_in_binary_mode(tmp_path):
    report = run(write_csv(tmp_path / "old.csv", SAMPLE), "scripted", analyzers=scripted(), mode="binary")
    # SAMPLE의 insufficient_information 정답 1행은 이진 지표에서 빠진다.
    assert "이진 지표에서 제외: 1건" in report
    assert "직접 채운 expected_binary 0, dangerous에서 파생 2, suspicious에서 파생 2, normal에서 파생 2" in report


def test_run_rejects_unknown_mode(tmp_path):
    with pytest.raises(DatasetError, match="평가 모드"):
        run(write_csv(tmp_path / "old.csv", SAMPLE), "scripted", analyzers=scripted(), mode="ternary")


def test_cli_mode_option(tmp_path):
    data, report = write_csv(tmp_path / "mixed.csv", MIXED, BINARY_COLUMNS), tmp_path / "report.md"
    done = subprocess.run([sys.executable, "evaluate.py", "--data", str(data), "--mode", "binary", "--split", "dev",
                           "--output", str(report)], cwd=BACKEND, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    assert "| 평가 모드 | binary" in report.read_text(encoding="utf-8")
    done = subprocess.run([sys.executable, "evaluate.py", "--data", str(data), "--split", "dev", "--output", str(report)],
                          cwd=BACKEND, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    assert "평가 모드" not in report.read_text(encoding="utf-8")
    done = subprocess.run([sys.executable, "evaluate.py", "--data", str(data), "--mode", "ternary"],
                          cwd=BACKEND, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode != 0


# ---- 학습 행 선택 ----

def test_training_excludes_binary_only_rows_under_own_key():
    rows = [erow("FAKE-1", None, "scam"), erow("FAKE-2", "insufficient_information")]
    data = model_training.select_training_rows(rows)
    assert data.excluded["no_level_label"] == 1 and data.excluded["insufficient_label"] == 1
    assert "no_level_label" not in model_training.select_training_rows([erow("FAKE-3", "insufficient_information")]).excluded
