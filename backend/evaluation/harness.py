"""평가 하네스: HANDOVER 4절 스키마의 CSV를 Analyzer로 판정하고 4단계 지표를 낸다.

리포트·예외 메시지에는 원문, URL, 라벨 근거를 넣지 않는다. 행은 id로만 가리킨다.
"""

import asyncio
import csv
import hashlib
import subprocess
from collections import Counter
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import ValidationError

from app.analyzers import Analyzer, CompositeAnalyzer, RuleBasedAnalyzer
from app.contracts import AnalysisInput, RiskLevel
from app.model_adapter import MODEL_PATH_ENV, load_configured_model
from app.url_reputation import DisconnectedReputationProvider

REQUIRED_COLUMNS = (
    "id", "text", "url", "expected_level", "label_reason", "source",
    "is_synthetic", "campaign_id", "split", "review_status",
)
LEVELS = tuple(level.value for level in RiskLevel)
SPLITS = ("dev", "test")
# 개발 중에는 dev만 돌리고 test는 마지막 비교에만 쓴다.
SPLIT_FILTERS = ("all", *SPLITS)
INPUT_TYPES = ("text", "url")
# 오류는 정보 부족으로 합치지 않고 별도 열로 센다.
ERROR_KINDS = ("input_error", "timeout", "analysis_error")
PREDICTION_COLUMNS = LEVELS + ERROR_KINDS
MODES = ("levels", "binary")
# 이진 평가: 선택 컬럼 expected_binary. 비어 있으면 expected_level에서 만든다.
BINARY_COLUMN = "expected_binary"
BINARY_LABELS = ("scam", "legit")
LEVEL_TO_BINARY = {
    RiskLevel.DANGEROUS.value: "scam",
    RiskLevel.SUSPICIOUS.value: "scam",
    RiskLevel.NORMAL.value: "legit",
}
WARNING_LEVELS = (RiskLevel.SUSPICIOUS.value, RiskLevel.DANGEROUS.value)
NO_WARNING_LEVELS = (RiskLevel.NORMAL.value, RiskLevel.INSUFFICIENT_INFORMATION.value)
# 경고 없음 열을 먼저, 경고함 열을 다음에, 오류 열은 따로 둔다.
BINARY_PREDICTION_COLUMNS = NO_WARNING_LEVELS + WARNING_LEVELS + ERROR_KINDS
# 이진 라벨 출처. suspicious에서 만든 scam은 정답이 불확실하다(사기라고 단정하기 어려움).
BINARY_SOURCES = {
    "direct": "직접 채운 expected_binary",
    "from_dangerous": "dangerous에서 파생",
    "from_suspicious": "suspicious에서 파생",
    "from_normal": "normal에서 파생",
}
TRUE_VALUES = {"true", "1", "yes", "y"}
FALSE_VALUES = {"false", "0", "no", "n"}

class DatasetError(ValueError):
    """평가셋 형식 오류. 메시지에 셀 값을 넣지 않는다."""


class AnalyzerSetupError(ValueError):
    """분석기를 준비하지 못함 (예: 모델 미설정·로드 실패). 경로를 넣지 않는다."""


def _rules_model_analyzer() -> Analyzer:
    # 모델 없이 조용히 규칙 결과만 비교되는 것을 막는다.
    state = load_configured_model()
    if state.status != "loaded":
        detail = f"{state.status}, {state.reason}" if state.reason else state.status
        raise AnalyzerSetupError(f"rules+model은 {MODEL_PATH_ENV}에 학습한 모델 폴더가 필요해요 ({detail}).")
    return CompositeAnalyzer(RuleBasedAnalyzer(DisconnectedReputationProvider("evaluation_offline")), state)


# 평가는 외부로 조회하지 않는다. 키 환경 변수가 있어도 미연결 어댑터를 직접 넣는다.
ANALYZERS: dict[str, Callable[[], Analyzer]] = {
    "rules": lambda: RuleBasedAnalyzer(DisconnectedReputationProvider("evaluation_offline")),
    "rules+model": _rules_model_analyzer,
}


@dataclass(frozen=True)
class EvalRow:
    id: str
    input_type: Literal["text", "url"]
    content: str = field(repr=False)
    # 4단계 라벨. 이진 라벨만 있는 행은 None이며 4단계 평가에서 제외한다.
    expected: str | None
    split: str
    is_synthetic: bool
    campaign_id: str
    review_status: str
    # 직접 채운 이진 라벨(scam/legit). 비어 있으면 None.
    expected_binary: str | None = None


def binary_label(row: EvalRow) -> tuple[str | None, str | None]:
    """(이진 라벨, 출처). 직접 채운 값이 우선이고, 없으면 4단계 라벨에서 만든다.

    정답이 insufficient_information이고 이진 라벨이 없으면 (None, None): 이진 평가에서 제외한다.
    """
    if row.expected_binary:
        return row.expected_binary, "direct"
    if row.expected in LEVEL_TO_BINARY:
        return LEVEL_TO_BINARY[row.expected], f"from_{row.expected}"
    return None, None


@dataclass(frozen=True)
class Outcome:
    row: EvalRow
    predicted: str
    policy_reason: str | None = None
    factor_codes: tuple[str, ...] = ()
    analysis_version: str | None = None
    model_stage: str | None = None


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
            has_binary_column = BINARY_COLUMN in (reader.fieldnames or [])
            binary = (record.get(BINARY_COLUMN) or "").strip()
            if (expected and expected not in LEVELS) or (not expected and not has_binary_column):
                raise DatasetError(f"{line}행: expected_level은 {'/'.join(LEVELS)} 중 하나여야 해요.")
            if binary and binary not in BINARY_LABELS:
                raise DatasetError(f"{line}행: expected_binary는 {'/'.join(BINARY_LABELS)} 중 하나여야 해요.")
            if not expected and not binary:
                raise DatasetError(f"{line}행: expected_level과 expected_binary가 모두 비어 있어요.")
            if binary and expected in LEVEL_TO_BINARY and LEVEL_TO_BINARY[expected] != binary:
                raise DatasetError(f"{line}행: expected_level과 expected_binary가 서로 맞지 않아요.")
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
                expected=expected or None,
                split=split,
                is_synthetic=_parse_bool(record["is_synthetic"] or "", line),
                campaign_id=(record["campaign_id"] or "").strip(),
                review_status=(record["review_status"] or "").strip(),
                expected_binary=binary or None,
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
        next((stage.status for stage in result.analysis_stages if stage.name == "lightweight_model"), None),
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
    split_filter: str = "all"
    # 모델이 있는 분석기만: 모델 버전, manifest의 모델·학습 CSV SHA-256, 임계값 상태.
    model: dict | None = None


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


def run_info(data_path: Path, analyzer: str, review_status_filter: str | None = None, repo: Path | None = None,
             split_filter: str = "all") -> RunInfo:
    commit, dirty = git_state(repo or Path(__file__).resolve().parents[2])
    return RunInfo(
        commit=commit, worktree_dirty=dirty, data_sha256=file_sha256(data_path), analyzer=analyzer,
        run_at=datetime.now().astimezone().isoformat(timespec="seconds"),
        review_status_filter=review_status_filter, split_filter=split_filter,
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


def _header_lines(outcomes: list[Outcome], info: RunInfo, excluded_by_filter: int, review_status_counts: Counter | None,
                  excluded_by_split: int, extra_info_rows: list[list[str]], extra_exclusion_lines: list[str]) -> list[str]:
    """두 모드가 함께 쓰는 머리말과 데이터 구성. 마지막 빈 줄까지 포함한다."""
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
            *extra_info_rows,
            ["analysis_version", ", ".join(versions) or "없음"],
            ["실행 시각", info.run_at],
            ["review_status 필터", info.review_status_filter or "없음 (전체)"],
            ["split 필터", "없음 (전체)" if info.split_filter == "all" else info.split_filter],
            *([["모델 버전", info.model.get("version")],
               ["모델 파일 SHA-256", f"`{info.model.get('model_sha256')}`"],
               ["임계값 상태", info.model.get("threshold_status") or "기록 없음"]] if info.model else []),
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
    if excluded_by_split:
        lines.append(f"- split 필터로 제외: {excluded_by_split}건")
    lines += extra_exclusion_lines
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
    if info.model:
        stages = Counter(o.model_stage or "(결과 없음)" for o in outcomes)
        lines.append("- 모델 단계 상태: " + (", ".join(f"{status} {count}" for status, count in sorted(stages.items())) or "없음"))
        if info.model.get("data_sha256") != info.data_sha256:
            lines.append("- 이 모델은 평가 CSV와 SHA-256이 다른 CSV로 학습했다. 학습 행과 평가 행의 겹침을 따로 확인한다.")
        elif info.split_filter != "test":
            lines.append("- **경고: dev 행은 모델 학습과 임계값 결정에 쓴 행이다(in-sample). dev 비교는 train-report.md의 OOF 결과를 쓴다.**")
    lines.append("")
    return lines


def _splits(info: RunInfo) -> tuple[str, ...]:
    return SPLITS if info.split_filter == "all" else (info.split_filter,)


def render_report(outcomes: list[Outcome], info: RunInfo, excluded_by_filter: int = 0,
                  review_status_counts: Counter | None = None, excluded_by_split: int = 0,
                  excluded_no_level: int = 0) -> str:
    exclusions = [f"- 4단계 라벨(expected_level) 없음으로 제외: {excluded_no_level}건"] if excluded_no_level else []
    lines = _header_lines(outcomes, info, excluded_by_filter, review_status_counts, excluded_by_split, [], exclusions)
    for split in _splits(info):
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
            # 정상 기대 사례가 위험으로 올라가는지 매 평가에서 실제·합성을 나눠 본다.
            for label, group in (("실제", [o for o in normal if not o.row.is_synthetic]), ("합성", [o for o in normal if o.row.is_synthetic])):
                spread = Counter(o.predicted for o in group)
                lines.append(f"- 판정 분포 ({label} {len(group)}건): " + (", ".join(
                    f"{column} {spread[column]}" for column in PREDICTION_COLUMNS if spread[column]) or "없음"))
            lines.append("")
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


# ---- 이진 평가 (경고함 = suspicious·dangerous, 경고 없음 = insufficient_information·normal) ----

@dataclass(frozen=True)
class BinaryMetrics:
    total: int
    confusion: dict[str, dict[str, int]]
    scam_total: int
    scam_warned: int
    scam_missed: int  # 경고 없음(정보 부족·정상). 오류 행은 넣지 않는다.
    scam_errors: int
    scam_dangerous: int
    legit_total: int
    legit_flagged: int  # 의심·위험 (오탐)
    legit_dangerous: int  # 위험 (심각한 오탐)
    legit_errors: int
    insufficient_predicted: int
    errors: int


def compute_binary_metrics(outcomes: Iterable[Outcome]) -> BinaryMetrics:
    """이진 라벨이 있는 행만 받는다. 분모는 오류 행을 포함한 해당 정답의 전체 행이다."""
    confusion = {label: {column: 0 for column in BINARY_PREDICTION_COLUMNS} for label in BINARY_LABELS}
    total = 0
    for outcome in outcomes:
        label, _ = binary_label(outcome.row)
        if label is None:
            raise ValueError("이진 라벨이 없는 행은 이진 지표에 넣지 않는다.")
        confusion[label][outcome.predicted] += 1
        total += 1
    scam, legit = confusion["scam"], confusion["legit"]
    insufficient = RiskLevel.INSUFFICIENT_INFORMATION.value
    return BinaryMetrics(
        total=total,
        confusion=confusion,
        scam_total=sum(scam.values()),
        scam_warned=sum(scam[level] for level in WARNING_LEVELS),
        scam_missed=sum(scam[level] for level in NO_WARNING_LEVELS),
        scam_errors=sum(scam[kind] for kind in ERROR_KINDS),
        scam_dangerous=scam[RiskLevel.DANGEROUS.value],
        legit_total=sum(legit.values()),
        legit_flagged=sum(legit[level] for level in WARNING_LEVELS),
        legit_dangerous=legit[RiskLevel.DANGEROUS.value],
        legit_errors=sum(legit[kind] for kind in ERROR_KINDS),
        insufficient_predicted=scam[insufficient] + legit[insufficient],
        errors=sum(confusion[label][kind] for label in BINARY_LABELS for kind in ERROR_KINDS),
    )


def _rate(numerator: int, denominator: int) -> str:
    return f"{numerator}/{denominator} = {_fmt(_ratio(numerator, denominator))}"


def _binary_section(title: str, outcomes: list[Outcome]) -> list[str]:
    lines = [f"#### {title} ({len(outcomes)}건)", ""]
    if not outcomes:
        return lines + ["해당 행 없음.", ""]
    m = compute_binary_metrics(outcomes)
    lines += ["이진 혼동행렬 (행: 정답, 열: 판정. 경고 없음 = normal·insufficient_information, 경고함 = suspicious·dangerous)", ""]
    lines += _table(
        ["정답 \\ 판정", *BINARY_PREDICTION_COLUMNS, "합계"],
        ([label, *m.confusion[label].values(), sum(m.confusion[label].values())] for label in BINARY_LABELS),
    )
    lines += [
        "",
        f"- 사기 경고율 (scam 중 의심·위험): {_rate(m.scam_warned, m.scam_total)} (분모에 오류 {m.scam_errors}건 포함)",
        f"- 사기 놓침 (scam 중 정보 부족·정상): {m.scam_missed}건",
        f"- 정상 오탐률 (legit 중 의심·위험): {_rate(m.legit_flagged, m.legit_total)} (분모에 오류 {m.legit_errors}건 포함)",
        f"- 정상 → 위험 (심각한 오탐): {m.legit_dangerous}건",
        f"- 사기 중 위험 판정 비율: {_rate(m.scam_dangerous, m.scam_total)}",
        f"- 정보 부족 판정 비율: {_rate(m.insufficient_predicted, m.total)}",
        f"- 오류 (입력 오류·시간 초과·분석 오류, 경고 없음으로 합치지 않음): {m.errors}건",
        "",
    ]
    return lines


def _binary_summary_row(name: str, outcomes: list[Outcome]) -> list[object]:
    m = compute_binary_metrics(outcomes)
    return [
        name, m.total, _rate(m.scam_warned, m.scam_total), _rate(m.legit_flagged, m.legit_total), m.legit_dangerous,
        _rate(m.scam_dangerous, m.scam_total), _rate(m.insufficient_predicted, m.total), m.errors,
    ]


def _binary_summary(outcomes: list[Outcome]) -> list[str]:
    by_source = {source: [o for o in outcomes if binary_label(o.row)[1] == source] for source in BINARY_SOURCES}
    groups = [
        ("전체", outcomes),
        ("실제", [o for o in outcomes if not o.row.is_synthetic]),
        ("합성", [o for o in outcomes if o.row.is_synthetic]),
        *((f"출처: {name}", by_source[source]) for source, name in BINARY_SOURCES.items()),
    ]
    lines = ["#### 구분별 지표", "",
             "건수/분모 = 비율. 분모는 오류 행을 포함한다. 출처별 줄은 전체 줄을 라벨 출처로 나눈 것이다.", ""]
    lines += _table(
        ["구분", "행", "사기 경고율", "정상 오탐률", "정상 → 위험", "사기 중 위험", "정보 부족 판정", "오류"],
        (_binary_summary_row(name, group) for name, group in groups),
    )
    lines += ["", "- suspicious에서 파생한 scam은 정답이 불확실하다 (라벨링 지침상 사기라고 단정하기 어려움).", ""]
    return lines


def _binary_id_table(title: str, outcomes: list[Outcome]) -> list[str]:
    lines = [f"#### {title} ({len(outcomes)}건)", ""]
    if outcomes:
        lines += _table(
            ["id", "입력", "라벨 출처", "판정", "policy_reason", "근거 신호"],
            ([o.row.id, o.row.input_type, BINARY_SOURCES[binary_label(o.row)[1]], o.predicted, o.policy_reason or "-",
              ", ".join(o.factor_codes) or "-"] for o in outcomes),
        )
        lines.append("")
    return lines


def render_binary_report(outcomes: list[Outcome], info: RunInfo, excluded_by_filter: int = 0,
                         review_status_counts: Counter | None = None, excluded_by_split: int = 0) -> str:
    labeled = [o for o in outcomes if binary_label(o.row)[0] is not None]
    unlabeled = [o for o in outcomes if binary_label(o.row)[0] is None]
    sources = Counter(binary_label(o.row)[1] for o in labeled)
    exclusions = [
        f"- 정답 insufficient_information + 이진 라벨 없음으로 이진 지표에서 제외: {len(unlabeled)}건 (분석은 했고 판정 분포만 split별로 표시)",
        "- 이진 라벨 출처: " + ", ".join(f"{name} {sources[source]}" for source, name in BINARY_SOURCES.items()),
    ]
    lines = _header_lines(outcomes, info, excluded_by_filter, review_status_counts, excluded_by_split,
                          [["평가 모드", "binary (경고함 = suspicious·dangerous, 경고 없음 = insufficient_information·normal)"]],
                          exclusions)
    for split in _splits(info):
        split_labeled = [o for o in labeled if o.row.split == split]
        lines += [f"## split: {split}", ""]
        if split == "test":
            lines += ["최종 테스트셋은 정책·임계값 조정에 쓰지 않는다.", ""]
        split_unlabeled = Counter(o.predicted for o in unlabeled if o.row.split == split)
        if split_unlabeled:
            lines += ["- 이진 지표 제외 행(정답 insufficient_information)의 판정 분포: " + ", ".join(
                f"{column} {split_unlabeled[column]}" for column in PREDICTION_COLUMNS if split_unlabeled[column]), ""]
        lines += _binary_section("전체", split_labeled)
        for input_type in INPUT_TYPES:
            lines += _binary_section(f"{input_type} 입력", [o for o in split_labeled if o.row.input_type == input_type])
        lines += _binary_summary(split_labeled)
        lines += _binary_id_table("놓친 사기 id (scam → 경고 없음)", [
            o for o in split_labeled if binary_label(o.row)[0] == "scam" and o.predicted in NO_WARNING_LEVELS])
        lines += _binary_id_table("정상 오탐 id (legit → 의심·위험)", [
            o for o in split_labeled if binary_label(o.row)[0] == "legit" and o.predicted in WARNING_LEVELS])
        lines += _binary_id_table("오류 id", [o for o in split_labeled if o.predicted in ERROR_KINDS])
    return "\n".join(lines)


def run(data_path: Path, analyzer_name: str = "rules", review_status: str | None = None,
        timeout: float = 5.0, analyzers: dict[str, Callable[[], Analyzer]] | None = None, split: str = "all",
        mode: str = "levels") -> str:
    registry = analyzers if analyzers is not None else ANALYZERS
    if analyzer_name not in registry:
        raise DatasetError(f"알 수 없는 분석기예요: {analyzer_name}")
    if split not in SPLIT_FILTERS:
        raise DatasetError(f"split 필터는 {'/'.join(SPLIT_FILTERS)} 중 하나여야 해요.")
    if mode not in MODES:
        raise DatasetError(f"평가 모드는 {'/'.join(MODES)} 중 하나여야 해요.")
    info = run_info(data_path, analyzer_name, review_status, split_filter=split)
    rows = load_rows(data_path)
    status_counts = Counter(row.review_status for row in rows)
    in_split = rows if split == "all" else [row for row in rows if row.split == split]
    selected = in_split if review_status is None else [row for row in in_split if row.review_status == review_status]
    analyzer = registry[analyzer_name]()
    model = getattr(getattr(analyzer, "model_state", None), "model", None)
    if model is not None:
        info = replace(info, model={"version": model.version, **getattr(model, "info", {})})
    excluded_by_filter, excluded_by_split = len(in_split) - len(selected), len(rows) - len(in_split)
    # split 밖의 행은 분석기에 넘기지 않는다.
    if mode == "binary":
        outcomes = evaluate(selected, analyzer, timeout)
        return render_binary_report(outcomes, info, excluded_by_filter, status_counts, excluded_by_split)
    # 4단계 라벨이 없는(이진 라벨만 있는) 행은 4단계 평가에서 빼고 건수만 알린다.
    with_level = [row for row in selected if row.expected is not None]
    outcomes = evaluate(with_level, analyzer, timeout)
    return render_report(outcomes, info, excluded_by_filter, status_counts, excluded_by_split,
                         len(selected) - len(with_level))
