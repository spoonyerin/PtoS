"""평가 하네스의 코드 동작 검증. 모든 샘플은 명백한 가짜 합성 문장이며 결과는 탐지 성능이 아니다."""

import asyncio
import csv
import hashlib
import socket
import subprocess
import sys
from pathlib import Path

import pytest

from app.contracts import AnalysisResult, InputAssessment, RiskLevel
from evaluation.harness import (
    REQUIRED_COLUMNS, DatasetError, EvalRow, Outcome, compute_metrics, evaluate, load_rows, render_report, run, RunInfo,
)

BACKEND = Path(__file__).resolve().parents[1]
FAKE = "[가짜 테스트 샘플]"


def fake_row(row_id, expected, split="dev", text="", url="", campaign="", synthetic="true", review="agreed"):
    return {
        "id": row_id, "text": text, "url": url, "expected_level": expected,
        "label_reason": f"{FAKE} 라벨 근거", "source": "synthetic-test-fixture", "is_synthetic": synthetic,
        "campaign_id": campaign, "split": split, "review_status": review,
    }


SAMPLE = [
    fake_row("FAKE-001", "dangerous", text=f"{FAKE} 가짜은행입니다. 인증번호를 알려주세요.", campaign="FAKE-C1"),
    fake_row("FAKE-002", "suspicious", text=f"{FAKE} 인증번호를 알려주세요."),
    fake_row("FAKE-003", "normal", text=f"{FAKE} 내일 오후 2시에 도서관에서 만나요."),
    fake_row("FAKE-004", "insufficient_information", url="https://fake-sample.invalid/x"),
    fake_row("FAKE-005", "dangerous", split="test", text=f"{FAKE} 가짜기관입니다. 계좌로 송금하세요.", campaign="FAKE-C1"),
    fake_row("FAKE-006", "normal", split="test", text=f"{FAKE} 택배가 문 앞에 도착했어요.", review="pending"),
    fake_row("FAKE-007", "suspicious", split="test", url="https://fake-sample.invalid/y"),
]


def write_csv(path, rows, columns=REQUIRED_COLUMNS):
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns), extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def result(level, reason="fake_policy"):
    return AnalysisResult(
        risk_level=level, risk_factors=[], explanation="", action_guidance=[], limitations=[],
        analysis_version="fake-v0", evidence=[], input_assessment=InputAssessment(status="sentence_present", reasons=[]),
        analysis_stages=[], policy_reason=reason, urls=[],
    )


class ScriptedAnalyzer:
    """content에 들어 있는 표식으로 판정·지연·예외를 흉내 내는 가짜 분석기."""

    async def analyze(self, data):
        if "SLOW" in data.content:
            await asyncio.sleep(1)
        if "BOOM" in data.content:
            raise RuntimeError(data.content)
        for level in RiskLevel:
            if f"<{level.value}>" in data.content:
                return result(level)
        return result(RiskLevel.INSUFFICIENT_INFORMATION)


def row(row_id, expected, input_type="text", split="dev", content="x", synthetic=True, campaign=""):
    return EvalRow(row_id, input_type, content, expected, split, synthetic, campaign, "agreed")


def outcome(expected, predicted, **kwargs):
    return Outcome(row("FAKE", expected, **kwargs), predicted)


@pytest.fixture
def no_network(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("evaluation must not open network connections")
    # Windows asyncio는 루프 생성 시 루프백 socketpair를 쓰므로 socket.connect는 막지 않는다.
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket, "getaddrinfo", forbidden)


def test_load_rows_parses_schema_and_input_type(tmp_path):
    rows = load_rows(write_csv(tmp_path / "fake.csv", SAMPLE))
    assert [r.id for r in rows] == [s["id"] for s in SAMPLE]
    assert rows[0].input_type == "text" and rows[3].input_type == "url"
    assert rows[3].content == "https://fake-sample.invalid/x"
    assert rows[4].split == "test" and rows[0].is_synthetic is True


def test_load_rows_accepts_excel_bom(tmp_path):
    path = tmp_path / "bom.csv"
    write_csv(path, SAMPLE[:1])
    path.write_bytes(b"\xef\xbb\xbf" + path.read_bytes())
    assert load_rows(path)[0].id == "FAKE-001"


def test_load_rows_same_result_with_and_without_bom(tmp_path):
    plain = write_csv(tmp_path / "plain.csv", SAMPLE)
    bom = tmp_path / "bom.csv"
    bom.write_bytes(b"\xef\xbb\xbf" + plain.read_bytes())
    assert not plain.read_bytes().startswith(b"\xef\xbb\xbf")
    assert load_rows(plain) == load_rows(bom)


def test_load_rows_ignores_extra_columns(tmp_path):
    rows = [{**r, "watermark_removed": "true"} for r in SAMPLE]
    extended = load_rows(write_csv(tmp_path / "extra.csv", rows, (*REQUIRED_COLUMNS, "watermark_removed")))
    assert extended == load_rows(write_csv(tmp_path / "base.csv", SAMPLE))


SECRET = f"{FAKE} 비밀원문-노출금지"


@pytest.mark.parametrize("rows, message", [
    ([fake_row("FAKE-1", "dangerous", text=SECRET), fake_row("FAKE-1", "normal", text=SECRET)], "id가 중복"),
    ([fake_row("FAKE-1", SECRET, text=SECRET)], "expected_level"),
    ([fake_row("FAKE-1", "normal", split=SECRET, text=SECRET)], "split"),
    ([fake_row("FAKE-1", "normal", text=SECRET, url="https://fake-sample.invalid/")], "하나만"),
    ([fake_row("FAKE-1", "normal", text="  ")], "모두 비어"),
    ([fake_row("FAKE-1", "normal", text=SECRET, synthetic=SECRET)], "is_synthetic"),
    ([fake_row("", "normal", text=SECRET)], "id가 비어"),
], ids=["duplicate", "level", "split", "text-and-url", "empty", "bool", "no-id"])
def test_load_rows_rejects_invalid_rows_without_echoing_cells(tmp_path, rows, message):
    with pytest.raises(DatasetError) as error:
        load_rows(write_csv(tmp_path / "bad.csv", rows))
    assert message in str(error.value)
    assert "비밀원문" not in str(error.value)


def test_load_rows_requires_all_columns(tmp_path):
    columns = [c for c in REQUIRED_COLUMNS if c != "campaign_id"]
    with pytest.raises(DatasetError, match="campaign_id"):
        load_rows(write_csv(tmp_path / "bad.csv", SAMPLE, columns))


def test_metrics_confusion_scores_and_miss_counts():
    outcomes = [
        outcome("dangerous", "dangerous"),
        outcome("dangerous", "suspicious"),
        outcome("dangerous", "insufficient_information"),
        outcome("dangerous", "timeout"),
        outcome("suspicious", "suspicious"),
        outcome("suspicious", "dangerous"),
        outcome("normal", "insufficient_information"),
        outcome("insufficient_information", "insufficient_information"),
    ]
    m = compute_metrics(outcomes)
    assert m.total == 8
    assert m.confusion["dangerous"] == {
        "normal": 0, "suspicious": 1, "dangerous": 1, "insufficient_information": 1,
        "input_error": 0, "timeout": 1, "analysis_error": 0,
    }
    d = m.scores["dangerous"]
    assert (d.precision, d.recall, d.support, d.predicted) == (0.5, 0.25, 4, 2)
    assert d.f1 == pytest.approx(2 * 0.5 * 0.25 / 0.75)
    # normal 판정이 하나도 없으면 Precision은 0이 아니라 정의 불가다.
    n = m.scores["normal"]
    assert (n.precision, n.recall, n.f1) == (None, 0.0, None)
    assert m.dangerous_missed == 1
    assert m.dangerous_to_insufficient == 1
    assert m.insufficient_predicted == 3
    assert m.insufficient_dangerous_ratio == pytest.approx(1 / 3)


def test_metrics_empty_and_zero_scores():
    m = compute_metrics([outcome("suspicious", "dangerous")])
    assert m.scores["suspicious"].f1 is None  # 판정 0건 → Precision N/A
    assert m.scores["dangerous"].f1 is None  # expected 0건 → Recall N/A
    assert m.insufficient_dangerous_ratio is None
    m = compute_metrics([outcome("suspicious", "dangerous"), outcome("dangerous", "suspicious")])
    assert m.scores["suspicious"].f1 == 0.0


def test_evaluate_separates_input_error_timeout_and_analysis_error():
    rows = [
        row("FAKE-1", "dangerous", content=f"{FAKE} <dangerous>"),
        row("FAKE-2", "dangerous", content="가" * 10_001),
        row("FAKE-3", "dangerous", content=f"{FAKE} SLOW"),
        row("FAKE-4", "dangerous", content=f"{FAKE} BOOM"),
        row("FAKE-5", "normal", input_type="url", content="not a url"),
    ]
    outcomes = evaluate(rows, ScriptedAnalyzer(), timeout=0.05)
    assert [o.predicted for o in outcomes] == ["dangerous", "input_error", "timeout", "analysis_error", "input_error"]
    assert outcomes[0].policy_reason == "fake_policy" and outcomes[0].analysis_version == "fake-v0"


def info(**kwargs):
    return RunInfo(**({"commit": "c0ffee", "worktree_dirty": False, "data_sha256": "ab" * 32,
                       "analyzer": "scripted", "run_at": "2026-10-26T12:00:00+09:00"} | kwargs))


def test_report_header_splits_input_types_and_normal_table():
    outcomes = [
        Outcome(row("FAKE-D1", "dangerous", content=SECRET), "suspicious"),
        Outcome(row("FAKE-N1", "normal", content=SECRET), "insufficient_information", "no_rule_signal", ("money_request",)),
        Outcome(row("FAKE-U1", "suspicious", input_type="url", content="https://fake-sample.invalid/secret-path"), "insufficient_information"),
        Outcome(row("FAKE-T1", "dangerous", split="test", content=SECRET), "dangerous"),
    ]
    report = render_report(outcomes, info())
    for expected in ("`c0ffee`", "`" + "ab" * 32 + "`", "| 분석기 | scripted |", "2026-10-26T12:00:00+09:00"):
        assert expected in report
    assert report.index("## split: dev") < report.index("## split: test")
    dev = report[report.index("## split: dev"):report.index("## split: test")]
    assert "#### text 입력 (2건)" in dev and "#### url 입력 (1건)" in dev
    assert "#### expected=normal 사례 (1건)" in dev
    assert "| FAKE-N1 | text | insufficient_information | no_rule_signal | money_request |" in dev
    assert "위험 → 정상·의심 미탐: 1건" in dev
    assert "합성 데이터만 평가했다" in report
    assert "비밀원문" not in report and "secret-path" not in report


def test_report_flags_campaign_leak_and_mixed_data():
    outcomes = [
        Outcome(row("FAKE-1", "dangerous", campaign="FAKE-C9"), "dangerous"),
        Outcome(row("FAKE-2", "dangerous", split="test", campaign="FAKE-C9", synthetic=False), "dangerous"),
    ]
    report = render_report(outcomes, info(worktree_dirty=True))
    assert "campaign_id 1개가 dev와 test에 함께" in report
    assert "FAKE-C9" not in report
    assert "합성 데이터만" not in report and "합성 행이 섞여" in report
    assert "커밋되지 않은 코드" in report


def test_run_with_rule_analyzer_offline_and_without_raw_text(tmp_path, no_network, monkeypatch):
    monkeypatch.setenv("GOOGLE_SAFE_BROWSING_API_KEY", "fake-key-for-test")
    path = write_csv(tmp_path / "fake.csv", SAMPLE)
    report = run(path, "rules", review_status=None)
    assert hashlib.sha256(path.read_bytes()).hexdigest() in report
    assert "| 분석기 | rules |" in report and "rules-reputation-dev-v2" in report
    assert "평가 행: 7건 (실제 0건, 합성 7건)" in report
    assert "expected=normal 사례 (1건)" in report
    assert "campaign_id 1개가 dev와 test에 함께" in report
    for sample in SAMPLE:
        for column in ("text", "url", "label_reason"):
            if sample[column]:
                assert sample[column] not in report
    assert FAKE not in report and "fake-sample.invalid" not in report and "fake-key-for-test" not in report


def test_run_review_status_filter(tmp_path, no_network):
    report = run(write_csv(tmp_path / "fake.csv", SAMPLE), "rules", review_status="agreed")
    assert "평가 행: 6건" in report and "review_status 필터로 제외: 1건" in report
    assert "agreed 6, pending 1" in report


def test_run_rejects_unknown_analyzer(tmp_path):
    with pytest.raises(DatasetError, match="분석기"):
        run(write_csv(tmp_path / "fake.csv", SAMPLE), "missing")


def test_run_accepts_other_analyzers(tmp_path):
    rows = [fake_row("FAKE-1", "dangerous", text=f"{FAKE} <dangerous>")]
    report = run(write_csv(tmp_path / "fake.csv", rows), "scripted", analyzers={"scripted": ScriptedAnalyzer})
    assert "| 분석기 | scripted |" in report and "fake-v0" in report


def test_cli_writes_report_and_hides_csv_errors(tmp_path):
    data, out = write_csv(tmp_path / "fake.csv", SAMPLE), tmp_path / "report.md"
    done = subprocess.run([sys.executable, "evaluate.py", "--data", str(data), "--output", str(out)],
                          cwd=BACKEND, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    assert "# PtoS 평가 리포트" in out.read_text(encoding="utf-8")
    bad = write_csv(tmp_path / "bad.csv", [fake_row("FAKE-1", SECRET, text=SECRET)])
    done = subprocess.run([sys.executable, "evaluate.py", "--data", str(bad)],
                          cwd=BACKEND, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode != 0 and "expected_level" in done.stderr and "비밀원문" not in done.stderr


def test_run_split_filter_evaluates_only_selected_split(tmp_path, no_network):
    seen = []

    class Recording(ScriptedAnalyzer):
        async def analyze(self, data):
            seen.append(data.content)
            return await super().analyze(data)

    path = write_csv(tmp_path / "fake.csv", SAMPLE)
    report = run(path, "recording", analyzers={"recording": Recording}, split="dev")
    assert len(seen) == 4 and all("송금" not in content for content in seen)
    assert "| split 필터 | dev |" in report and "split 필터로 제외: 3건" in report
    assert "## split: dev" in report and "## split: test" not in report
    seen.clear()
    report = run(path, "recording", analyzers={"recording": Recording}, split="test")
    assert len(seen) == 3 and "## split: dev" not in report and "## split: test" in report


def test_run_split_defaults_to_all_and_rejects_unknown(tmp_path, no_network):
    path = write_csv(tmp_path / "fake.csv", SAMPLE)
    report = run(path, "scripted", analyzers={"scripted": ScriptedAnalyzer})
    assert "| split 필터 | 없음 (전체) |" in report and "split 필터로 제외" not in report
    assert "## split: dev" in report and "## split: test" in report
    with pytest.raises(DatasetError, match="split"):
        run(path, "scripted", analyzers={"scripted": ScriptedAnalyzer}, split="train")


def test_report_shows_normal_distribution_by_real_and_synthetic():
    outcomes = [
        outcome("normal", "suspicious", synthetic=False),
        outcome("normal", "insufficient_information", synthetic=False),
        outcome("normal", "dangerous"),
    ]
    info = RunInfo("abc", False, "0" * 64, "fake", "2026-01-01T00:00:00+09:00")
    report = render_report(outcomes, info)
    assert "판정 분포 (실제 2건): suspicious 1, insufficient_information 1" in report
    assert "판정 분포 (합성 1건): dangerous 1" in report


def test_cli_split_option(tmp_path):
    data, out = write_csv(tmp_path / "fake.csv", SAMPLE), tmp_path / "report.md"
    done = subprocess.run([sys.executable, "evaluate.py", "--data", str(data), "--split", "dev", "--output", str(out)],
                          cwd=BACKEND, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode == 0, done.stderr
    assert "| split 필터 | dev |" in out.read_text(encoding="utf-8")
    done = subprocess.run([sys.executable, "evaluate.py", "--data", str(data), "--split", "train"],
                          cwd=BACKEND, capture_output=True, text=True, encoding="utf-8")
    assert done.returncode != 0
