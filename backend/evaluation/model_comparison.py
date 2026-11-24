"""경량 모델 후보의 dev 교차검증 비교 (T5c 준비, 개발용).

- 같은 dev 행, 같은 시드·fold(campaign_id 기준)로 후보마다 out-of-fold(OOF) 점수를 내고 집계만 비교한다.
- 모델 파일을 저장하지 않고 서버가 쓰는 모델도 바꾸지 않는다. 어느 모델을 쓸지는 팀이 정한다(AGENTS.md 결정 필요 3).
- test 행은 읽은 직후 버린다. 리포트에는 집계만 넣고 원문·URL·id·campaign 값을 넣지 않는다.
- 후보는 내려받을 것이 없는 scikit-learn 구성뿐이다. 트랜스포머 후보는 여기에 없다.
"""

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.contracts import RiskLevel
from app.model_adapter import file_sha256

from .harness import BinaryMetrics, DatasetError, _fmt, _rate, _table, compute_binary_metrics, git_state, load_rows
from .model_training import (
    DEFAULT_CONFIG, TrainingError, TrainingSet, _library_versions, build_pipeline, choose_threshold, cross_validate,
    model_counts, oof_outcomes, score_texts, select_training_rows,
)

BASELINE = "tfidf-char_wb-2-4-lr"
_LR = DEFAULT_CONFIG["classifier"]
# 개발용 비교 후보. 성능 근거로 고른 목록이 아니며 채택을 뜻하지 않는다.
CANDIDATES: dict[str, dict] = {
    BASELINE: {
        "description": "현재 기준선: 어절 경계 문자 n-gram(2~4) + 로지스틱 회귀",
        "config": DEFAULT_CONFIG,
    },
    "tfidf-char-1-3-lr": {
        "description": "어절 경계를 넘는 문자 n-gram(1~3) + 로지스틱 회귀",
        "config": {"vectorizer": {"analyzer": "char", "ngram_range": [1, 3], "min_df": 1, "sublinear_tf": True},
                   "classifier": _LR},
    },
    "tfidf-word-1-2-lr": {
        "description": "공백 기준 어절 n-gram(1~2) + 로지스틱 회귀",
        "config": {"vectorizer": {"analyzer": "word", "token_pattern": r"(?u)\S+", "ngram_range": [1, 2], "min_df": 1,
                                  "sublinear_tf": True},
                   "classifier": _LR},
    },
    "tfidf-char_wb-2-4-nb": {
        "description": "어절 경계 문자 n-gram(2~4) + 다항 나이브 베이즈",
        "config": {"vectorizer": DEFAULT_CONFIG["vectorizer"], "classifier_type": "multinomial_nb",
                   "classifier": {"alpha": 1.0}},
    },
}


def build_candidate(config: dict, seed: int):
    if config.get("classifier_type") != "multinomial_nb":
        return build_pipeline(config, seed)
    from sklearn.feature_extraction.text import TfidfVectorizer
    from sklearn.naive_bayes import MultinomialNB
    from sklearn.pipeline import Pipeline

    vectorizer = dict(config["vectorizer"], ngram_range=tuple(config["vectorizer"]["ngram_range"]))
    return Pipeline([("tfidf", TfidfVectorizer(**vectorizer)), ("clf", MultinomialNB(**config["classifier"]))])


@dataclass(frozen=True)
class CandidateResult:
    name: str
    description: str
    threshold: float | None
    counts: dict[str, int]
    roc_auc: float | None
    average_precision: float | None
    combined: BinaryMetrics
    raised: int  # 규칙의 정보 부족이 모델 신호로 의심이 된 행 수
    cv_seconds: float
    # 학습에서 뺀 출처 행(있을 때만): 학습 행 전체로 학습한 모델의 신호 집계와 종합 판정.
    held_counts: dict[str, int] | None = None
    held_combined: BinaryMetrics | None = None
    held_raised: int = 0


@dataclass(frozen=True)
class Comparison:
    info: dict
    data: TrainingSet
    rules_only: BinaryMetrics
    candidates: list[CandidateResult]
    held_rules_only: BinaryMetrics | None = None


def _ranking_scores(scores: list[float], labels: list[int]) -> tuple[float | None, float | None]:
    """임계값과 무관한 순위 지표. 한 라벨만 있으면 계산하지 않는다."""
    if len(set(labels)) < 2:
        return None, None
    from sklearn.metrics import average_precision_score, roc_auc_score
    return float(roc_auc_score(labels, scores)), float(average_precision_score(labels, scores))


def _raised(rules_only, combined) -> int:
    return sum(r.predicted == RiskLevel.INSUFFICIENT_INFORMATION.value and c.predicted == RiskLevel.SUSPICIOUS.value
               for r, c in zip(rules_only, combined))


def compare(data_path: Path, seed: int, n_splits: int, label_source: str = "levels", names: list[str] | None = None,
            timeout: float = 5.0, pipeline_factory: Callable[[dict, int], object] = build_candidate,
            exclude_sources: tuple[str, ...] | list[str] = (),
            extra_candidates: dict[str, dict] | None = None) -> Comparison:
    """extra_candidates: 이름 → {description, config, factory}. 임베딩 후보처럼 따로 준비한 후보를 같은 fold로 비교한다."""
    candidates = {**CANDIDATES, **(extra_candidates or {})}
    names = list(names) if names else list(candidates)
    unknown = [name for name in names if name not in candidates]
    if unknown:
        raise TrainingError(f"알 수 없는 후보예요: {', '.join(unknown)}")
    if len(set(names)) != len(names):
        raise TrainingError("같은 후보를 두 번 지정했어요.")
    data_sha = file_sha256(data_path)
    rows = load_rows(data_path)
    data = select_training_rows(rows, label_source, exclude_sources)
    del rows  # test 행 원문을 더 들고 있지 않는다.
    if not data.rows:
        raise DatasetError("비교할 dev 행이 없어요.")
    # 첫 후보의 시간에 라이브러리 로드 시간이 섞이지 않게 먼저 불러 둔다.
    import sklearn.feature_extraction.text, sklearn.linear_model, sklearn.model_selection  # noqa: E401, F401
    import sklearn.naive_bayes, sklearn.pipeline  # noqa: E401, F401

    held = data.held_out if data.held_out is not None and data.held_out.rows else None
    rules_metrics, held_rules_metrics, results = None, None, []
    for name in names:
        config = candidates[name]["config"]
        factory = candidates[name].get("factory", pipeline_factory)
        started = time.perf_counter()
        # 분할은 라벨·campaign·시드로만 정해지므로 모든 후보가 같은 fold를 쓴다.
        scores, _ = cross_validate(data, config, seed, n_splits, factory)
        elapsed = time.perf_counter() - started
        threshold = choose_threshold(scores, data.labels)
        rules_only, combined = asyncio.run(oof_outcomes(data, scores, threshold, name, timeout))
        if rules_metrics is None:
            rules_metrics = compute_binary_metrics(rules_only)
        roc_auc, average_precision = _ranking_scores(scores, data.labels)
        held_fields = {}
        if held is not None:
            # 학습에서 뺀 출처 행은 학습 행 전체로 학습한 모델로 채점만 한다. 임계값은 학습 행의 OOF로 이미 정했다.
            final = factory(config, seed)
            final.fit(data.texts, data.labels)
            held_scores = score_texts(final, held.texts)
            held_rules, held_combined = asyncio.run(oof_outcomes(held, held_scores, threshold, name, timeout))
            if held_rules_metrics is None:
                held_rules_metrics = compute_binary_metrics(held_rules)
            held_fields = {"held_counts": model_counts(held_scores, held.labels, threshold),
                           "held_combined": compute_binary_metrics(held_combined),
                           "held_raised": _raised(held_rules, held_combined)}
        results.append(CandidateResult(name, candidates[name]["description"], threshold,
                                       model_counts(scores, data.labels, threshold), roc_auc, average_precision,
                                       compute_binary_metrics(combined), _raised(rules_only, combined), elapsed,
                                       **held_fields))
    commit, dirty = git_state(Path(__file__).resolve().parents[2])
    info = {"code_commit": commit, "worktree_dirty": dirty, "data_sha256": data_sha, "seed": seed, "n_splits": n_splits,
            "label_source": label_source, "excluded_sources": list(data.excluded_sources), "libraries": _library_versions(),
            "created_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    return Comparison(info, data, rules_metrics, results, held_rules_metrics)


def _combined_row(name: str, m: BinaryMetrics, raised: object) -> list[object]:
    return [name, _rate(m.scam_warned, m.scam_total), m.scam_missed, _rate(m.legit_flagged, m.legit_total),
            m.legit_dangerous, raised, m.errors]


def render_comparison_report(result: Comparison) -> str:
    info, data = result.info, result.data
    positive, negative = sum(data.labels), len(data.labels) - sum(data.labels)
    lines = [
        "# PtoS 경량 모델 후보 비교 (dev 교차검증)", "",
        *_table(["항목", "값"], [
            ["코드 커밋", f"`{info['code_commit']}`"],
            ["작업 트리", {True: "변경 있음", False: "변경 없음", None: "확인 불가"}[info["worktree_dirty"]]],
            ["평가 CSV SHA-256", f"`{info['data_sha256']}`"],
            ["시드 / fold 수", f"{info['seed']} / {info['n_splits']}"],
            ["라벨 기준", info["label_source"]],
            ["학습에서 뺀 출처", ", ".join(info["excluded_sources"]) or "없음"],
            ["라이브러리", ", ".join(f"{k} {v}" for k, v in info["libraries"].items())],
            ["실행 시각", info["created_at"]],
        ]), "",
        "**(dev, 후보 비교와 임계값 결정에 쓴 데이터라 부풀려진 수치)** 탐지 성능 수치가 아니다.",
        "같은 평가 CSV SHA-256·같은 라벨 기준·같은 시드와 fold 수의 리포트끼리만 비교한다.",
        "어느 모델을 쓸지는 팀이 정한다. 이 리포트는 후보를 채택하지 않으며 모델 파일을 만들지 않는다.",
        "기본 후보는 scikit-learn 구성이다. 임베딩 후보는 --embedding으로 따로 지정했을 때만 표에 나온다.",
        "리포트에는 집계만 넣고 원문·URL·id·campaign 값을 넣지 않는다.", "",
        "## 데이터", "",
        f"- 비교에 쓴 dev 행: {len(data.rows)}건 (사기 {positive}, 정상 {negative}), campaign {len(set(data.groups))}개",
        f"- 합성 {sum(r.is_synthetic for r in data.rows)}건, 실제 {sum(not r.is_synthetic for r in data.rows)}건",
        f"- test 행: {data.test_rows_dropped}건은 읽은 직후 버렸다.",
        "- 제외: " + ", ".join(f"{k} {v}" for k, v in data.excluded.items()), "",
        "## 후보", "",
        *_table(["후보", "구성"], ([c.name, c.description] for c in result.candidates)), "",
        "## 모델 단독 (OOF)", "",
        "임계값 기준(임시): 정상 라벨 행 모델 신호 0건을 지키며 사기 재현율 최대. 후보마다 같은 OOF 점수로 골라 낙관적이다.",
        "ROC AUC와 평균 정밀도는 임계값과 무관한 순위 지표다. 교차검증 시간은 한 번 잰 참고값이다.", "",
        *_table(["후보", "임계값", "사기 신호", "정상 신호", "ROC AUC", "평균 정밀도", "교차검증(초)"], (
            [c.name, _fmt(c.threshold) if c.threshold is not None else "찾지 못함",
             _rate(c.counts["tp"], c.counts["tp"] + c.counts["fn"]), _rate(c.counts["fp"], c.counts["fp"] + c.counts["tn"]),
             _fmt(c.roc_auc), _fmt(c.average_precision), f"{c.cv_seconds:.2f}"] for c in result.candidates)), "",
        "## 종합 판정 (같은 dev 행, 모델 점수는 OOF)", "",
        "현재 임시 정책 그대로다: 모델은 규칙의 정보 부족을 의심으로 올릴 수만 있다. 경고함 = 의심·위험.", "",
        *_table(["분석기", "사기 경고율", "사기 놓침", "정상 오탐률", "정상 → 위험", "정보 부족 → 의심", "오류"], [
            _combined_row("rules", result.rules_only, "-"),
            *(_combined_row(f"rules+{c.name}", c.combined, c.raised) for c in result.candidates),
        ]), "",
    ]
    if result.held_rules_only is not None:
        held = data.held_out
        lines += [
            "## 학습에서 뺀 출처 행 (학습·교차검증·임계값에 쓰지 않음)", "",
            f"- {len(held.rows)}건 (사기 {sum(held.labels)}, 정상 {len(held.labels) - sum(held.labels)}). "
            "후보마다 위의 학습 행 전체로 학습한 모델과 위 임계값으로 채점했다.",
            "- 위 표는 학습에 쓴 행만의 OOF 값이고, 아래 표는 학습에 쓰지 않은 행만의 값이다. 두 값을 섞어 말하지 않는다.",
            "- **(dev, 부풀려진 수치)** 학습에는 쓰지 않았지만 규칙 보강에는 쓴 dev 행이다.", "",
            *_table(["후보", "사기 신호", "정상 신호"], (
                [c.name, _rate(c.held_counts["tp"], c.held_counts["tp"] + c.held_counts["fn"]),
                 _rate(c.held_counts["fp"], c.held_counts["fp"] + c.held_counts["tn"])] for c in result.candidates)), "",
            *_table(["분석기", "사기 경고율", "사기 놓침", "정상 오탐률", "정상 → 위험", "정보 부족 → 의심", "오류"], [
                _combined_row("rules", result.held_rules_only, "-"),
                *(_combined_row(f"rules+{c.name}", c.held_combined, c.held_raised) for c in result.candidates),
            ]), "",
        ]
    return "\n".join(lines)
