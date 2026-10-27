"""평가 하네스: HANDOVER 4절 스키마의 CSV를 Analyzer로 판정하고 4단계 지표를 낸다.

리포트·예외 메시지에는 원문, URL, 라벨 근거를 넣지 않는다. 행은 id로만 가리킨다.
"""

import asyncio
import csv
import hashlib
import subprocess
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from app.analyzers import Analyzer, RuleBasedAnalyzer
from app.contracts import AnalysisInput, RiskLevel
from app.url_reputation import DisconnectedReputationProvider

REQUIRED_COLUMNS = (
    "id", "text", "url", "expected_level", "label_reason", "source",
    "is_synthetic", "campaign_id", "split", "review_status",
)
LEVELS = tuple(level.value for level in RiskLevel)
SPLITS = ("dev", "test")
INPUT_TYPES = ("text", "url")
# 오류는 정보 부족으로 합치지 않고 별도 열로 센다.
ERROR_KINDS = ("input_error", "timeout", "analysis_error")
PREDICTION_COLUMNS = LEVELS + ERROR_KINDS
TRUE_VALUES = {"true", "1", "yes", "y"}
FALSE_VALUES = {"false", "0", "no", "n"}

# 평가는 외부로 조회하지 않는다. 키 환경 변수가 있어도 미연결 어댑터를 직접 넣는다.
ANALYZERS: dict[str, Callable[[], Analyzer]] = {
    "rules": lambda: RuleBasedAnalyzer(DisconnectedReputationProvider("evaluation_offline")),
}


class DatasetError(ValueError):
    """평가셋 형식 오류. 메시지에 셀 값을 넣지 않는다."""


@dataclass(frozen=True)
class EvalRow:
    id: str
    input_type: Literal["text", "url"]
    content: str = field(repr=False)
    expected: str
    split: str
    is_synthetic: bool
    campaign_id: str
    review_status: str


@dataclass(frozen=True)
class Outcome:
    row: EvalRow
    predicted: str
    policy_reason: str | None = None
    factor_codes: tuple[str, ...] = ()
    analysis_version: str | None = None


def _parse_bool(value: str, line: int) -> bool:
    normalized = value.strip().lower()
    if normalized in TRUE_VALUES:
        return True
    if normalized in FALSE_VALUES:
        return False
    raise DatasetError(f"{line}행: is_synthetic은 true/false 중 하나여야 해요.")


def load_rows(path: Path) -> list[EvalRow]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = [name for name in REQUIRED_COLUMNS if name not in (reader.fieldnames or [])]
        if missing:
            raise DatasetError(f"필수 컬럼이 없어요: {', '.join(missing)}")
        rows: list[EvalRow] = []
        seen: set[str] = set()
        for line, record in enumerate(reader, start=2):
            if None in record:
                raise DatasetError(f"{line}행: 헤더보다 셀이 많아요.")
            row_id = (record["id"] or "").strip()
            if not row_id:
                raise DatasetError(f"{line}행: id가 비어 있어요.")
            if row_id in seen:
                raise DatasetError(f"{line}행: id가 중복돼요.")
            seen.add(row_id)
            expected = (record["expected_level"] or "").strip()
            if expected not in LEVELS:
                raise DatasetError(f"{line}행: expected_level은 {'/'.join(LEVELS)} 중 하나여야 해요.")
            split = (record["split"] or "").strip()
            if split not in SPLITS:
                raise DatasetError(f"{line}행: split은 {'/'.join(SPLITS)} 중 하나여야 해요.")
            text, url = record["text"] or "", record["url"] or ""
            has_text, has_url = bool(text.strip()), bool(url.strip())
            if has_text and has_url:
                raise DatasetError(f"{line}행: text와 url 중 하나만 채워야 해요.")
            if not has_text and not has_url:
                raise DatasetError(f"{line}행: text와 url이 모두 비어 있어요.")
            rows.append(EvalRow(
                id=row_id,
                input_type="text" if has_text else "url",
                content=text if has_text else url.strip(),
                expected=expected,
                split=split,
                is_synthetic=_parse_bool(record["is_synthetic"] or "", line),
                campaign_id=(record["campaign_id"] or "").strip(),
                review_status=(record["review_status"] or "").strip(),
            ))
    return rows


async def _analyze_one(analyzer: Analyzer, row: EvalRow, timeout: float) -> Outcome:
    try:
        data = AnalysisInput(input_type=row.input_type, content=row.content)
    except ValidationError:
        # 검증 오류 문자열에는 입력값이 들어가므로 기록하지 않는다.
        return Outcome(row, "input_error")
    try:
        async with asyncio.timeout(timeout):
            result = await analyzer.analyze(data)
    except TimeoutError:
        return Outcome(row, "timeout")
    except Exception:
        return Outcome(row, "analysis_error")
    return Outcome(
        row, result.risk_level.value, result.policy_reason,
        tuple(dict.fromkeys(item.factor_code.value for item in result.evidence)),
        result.analysis_version,
    )


async def evaluate_async(rows: Iterable[EvalRow], analyzer: Analyzer, timeout: float = 5.0) -> list[Outcome]:
    return [await _analyze_one(analyzer, row, timeout) for row in rows]


def evaluate(rows: Iterable[EvalRow], analyzer: Analyzer, timeout: float = 5.0) -> list[Outcome]:
    return asyncio.run(evaluate_async(rows, analyzer, timeout))


@dataclass(frozen=True)
class ClassScore:
    precision: float | None
    recall: float | None
    f1: float | None
    support: int
    predicted: int


@dataclass(frozen=True)
class Metrics:
    total: int
    confusion: dict[str, dict[str, int]]
    scores: dict[str, ClassScore]
    dangerous_missed: int
    dangerous_to_insufficient: int
    insufficient_predicted: int
    insufficient_dangerous_ratio: float | None


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def compute_metrics(outcomes: Iterable[Outcome]) -> Metrics:
    confusion = {expected: {column: 0 for column in PREDICTION_COLUMNS} for expected in LEVELS}
    total = 0
    for outcome in outcomes:
        confusion[outcome.row.expected][outcome.predicted] += 1
        total += 1
    scores = {}
    for level in LEVELS:
        hit = confusion[level][level]
        predicted = sum(confusion[expected][level] for expected in LEVELS)
        # 오류 행도 해당 클래스를 맞히지 못한 것이므로 support(재현율 분모)에 포함한다.
        support = sum(confusion[level].values())
        precision, recall = _ratio(hit, predicted), _ratio(hit, support)
        if precision is None or recall is None:
            f1 = None
        else:
            f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        scores[level] = ClassScore(precision, recall, f1, support, predicted)
    dangerous = confusion[RiskLevel.DANGEROUS.value]
    insufficient = RiskLevel.INSUFFICIENT_INFORMATION.value
    insufficient_predicted = sum(confusion[expected][insufficient] for expected in LEVELS)
    return Metrics(
        total=total,
        confusion=confusion,
        scores=scores,
        dangerous_missed=dangerous[RiskLevel.NORMAL.value] + dangerous[RiskLevel.SUSPICIOUS.value],
        dangerous_to_insufficient=dangerous[insufficient],
        insufficient_predicted=insufficient_predicted,
        insufficient_dangerous_ratio=_ratio(dangerous[insufficient], insufficient_predicted),
    )


@dataclass(frozen=True)
class RunInfo:
    commit: str
    worktree_dirty: bool | None
    data_sha256: str
    analyzer: str
    run_at: str
    review_status_filter: str | None = None


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_state(repo: Path) -> tuple[str, bool | None]:
    try:
        commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True).stdout.strip()
        status = subprocess.run(["git", "status", "--porcelain"], cwd=repo, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return "unknown", None
    return commit, bool(status.strip())


def run_info(data_path: Path, analyzer: str, review_status_filter: str | None = None, repo: Path | None = None) -> RunInfo:
    commit, dirty = git_state(repo or Path(__file__).resolve().parents[2])
    return RunInfo(
        commit=commit, worktree_dirty=dirty, data_sha256=file_sha256(data_path), analyzer=analyzer,
        run_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        review_status_filter=review_status_filter,
    )


def _fmt(value: float | None) -> str:
    return "N/A" if value is None else f"{value:.3f}"


def _table(header: Iterable[str], rows: Iterable[Iterable[object]]) -> list[str]:
    header = list(header)
    lines = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines


def _metrics_section(title: str, outcomes: list[Outcome]) -> list[str]:
    lines = [f"#### {title} ({len(outcomes)}건)", ""]
    if not outcomes:
        return lines + ["해당 행 없음.", ""]
    metrics = compute_metrics(outcomes)
    lines += ["혼동행렬 (행: expected, 열: 판정)", ""]
    lines += _table(
        ["expected \\ 판정", *PREDICTION_COLUMNS, "합계"],
        ([level, *metrics.confusion[level].values(), sum(metrics.confusion[level].values())] for level in LEVELS),
    )
    lines += ["", "클래스별 지표 (오류 행은 재현율 분모에 포함, 판정이 없으면 Precision N/A)", ""]
    lines += _table(
        ["클래스", "Precision", "Recall", "F1", "expected 수", "판정 수"],
        ([level, _fmt(s.precision), _fmt(s.recall), _fmt(s.f1), s.support, s.predicted] for level, s in metrics.scores.items()),
    )
    lines += [
        "",
        f"- 위험 → 정상·의심 미탐: {metrics.dangerous_missed}건",
        f"- 위험 → 정보 부족: {metrics.dangerous_to_insufficient}건 (위 미탐 수와 별도)",
        f"- 정보 부족 판정 {metrics.insufficient_predicted}건 중 expected=dangerous 비율: {_fmt(metrics.insufficient_dangerous_ratio)}",
        "",
    ]
    return lines


def render_report(outcomes: list[Outcome], info: RunInfo, excluded_by_filter: int = 0,
                  review_status_counts: Counter | None = None) -> str:
    dirty = {True: "변경 있음 (커밋되지 않은 코드로 실행)", False: "변경 없음", None: "확인 불가"}[info.worktree_dirty]
    versions = sorted({o.analysis_version for o in outcomes if o.analysis_version})
    synthetic = sum(o.row.is_synthetic for o in outcomes)
    lines = [
        "# PtoS 평가 리포트",
        "",
        *_table(["항목", "값"], [
            ["코드 커밋", f"`{info.commit}`"],
            ["작업 트리", dirty],
            ["평가 CSV SHA-256", f"`{info.data_sha256}`"],
            ["분석기", info.analyzer],
            ["analysis_version", ", ".join(versions) or "없음"],
            ["실행 시각", info.run_at],
            ["review_status 필터", info.review_status_filter or "없음 (전체)"],
        ]),
        "",
        "리포트에는 원문·URL·라벨 근거를 넣지 않는다. 행은 id로만 표시한다.",
        "",
        "## 데이터 구성",
        "",
        f"- 평가 행: {len(outcomes)}건 (실제 {len(outcomes) - synthetic}건, 합성 {synthetic}건)",
    ]
    if excluded_by_filter:
        lines.append(f"- review_status 필터로 제외: {excluded_by_filter}건")
    if review_status_counts:
        lines.append("- review_status별 행 수 (필터 전): " + ", ".join(
            f"{status or '(빈 값)'} {count}" for status, count in sorted(review_status_counts.items())))
    if outcomes and synthetic == len(outcomes):
        lines.append("- **합성 데이터만 평가했다. 이 결과는 탐지 성능 수치가 아니다.**")
    elif synthetic:
        lines.append("- 합성 행이 섞여 있다. 탐지 성능을 주장할 때는 실제·합성 구성을 함께 밝힌다.")
    campaigns = {split: {o.row.campaign_id for o in outcomes if o.row.split == split and o.row.campaign_id} for split in SPLITS}
    leaked = campaigns["dev"] & campaigns["test"]
    if leaked:
        lines.append(f"- **경고: campaign_id {len(leaked)}개가 dev와 test에 함께 있다. 분할 누출 가능성.**")
    lines.append("")
    for split in SPLITS:
        split_outcomes = [o for o in outcomes if o.row.split == split]
        lines += [f"## split: {split}", ""]
        if split == "test":
            lines += ["최종 테스트셋은 정책·임계값 조정에 쓰지 않는다.", ""]
        lines += _metrics_section("전체", split_outcomes)
        for input_type in INPUT_TYPES:
            lines += _metrics_section(f"{input_type} 입력", [o for o in split_outcomes if o.row.input_type == input_type])
        normal = [o for o in split_outcomes if o.row.expected == RiskLevel.NORMAL.value]
        lines += [
            f"#### expected=normal 사례 ({len(normal)}건)", "",
            "현재 분석기는 normal을 반환하지 않는다 (AGENTS.md 판정 계약). normal 기대 사례가 무엇으로 판정됐는지 따로 본다.", "",
        ]
        if normal:
            lines += _table(
                ["id", "입력", "판정", "policy_reason", "근거 신호"],
                ([o.row.id, o.row.input_type, o.predicted, o.policy_reason or "-", ", ".join(o.factor_codes) or "-"] for o in normal),
            )
            lines.append("")
        wrong = [o for o in split_outcomes if o.predicted != o.row.expected]
        lines += [f"#### 불일치 id ({len(wrong)}건)", ""]
        if wrong:
            lines += _table(["id", "입력", "expected", "판정"], ([o.row.id, o.row.input_type, o.row.expected, o.predicted] for o in wrong))
        lines.append("")
    return "\n".join(lines)


def run(data_path: Path, analyzer_name: str = "rules", review_status: str | None = None,
        timeout: float = 5.0, analyzers: dict[str, Callable[[], Analyzer]] | None = None) -> str:
    registry = analyzers if analyzers is not None else ANALYZERS
    if analyzer_name not in registry:
        raise DatasetError(f"알 수 없는 분석기예요: {analyzer_name}")
    info = run_info(data_path, analyzer_name, review_status)
    rows = load_rows(data_path)
    status_counts = Counter(row.review_status for row in rows)
    selected = rows if review_status is None else [row for row in rows if row.review_status == review_status]
    outcomes = evaluate(selected, registry[analyzer_name](), timeout)
    return render_report(outcomes, info, len(rows) - len(selected), status_counts)
