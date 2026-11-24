"""학습 전용 데이터로 후보 모델을 학습하고 dev로만 비교한다 (2026-11-24, 임시, 팀 확정 필요).

- 학습: 저장소 밖 파인튜닝 세트(finetune-*-train.csv: text, label(1=사기), source, ...). 평가셋 행은 학습에 쓰지 않는다.
  학습 조절(조기 종료 등)은 같은 세트의 -val.csv만 쓴다. 그 점수는 같은 출처 안의 점수라 부풀려져 있다.
- 비교·임계값: 평가 CSV의 split=dev 행(이진 라벨)만. test 행은 읽은 직후 버린다.
- 임계값(cross-fitted): dev를 campaign 단위 k-fold로 나누고, 다른 fold에서 고른 임계값을 해당 fold에 적용한다.
  임계값을 고른 행으로 점수를 매기지 않는다. 서버에 쓸 최종 임계값은 dev 전체에서 같은 기준으로 고른다.
  기준은 model_training과 같다(정상 행 모델 신호 0건을 지키며 사기 재현율 최대, 정상 임계값 = 사기 점수 최솟값).
- 모델 입력: URL 구간 → <URL>, 그 뒤 전화번호·긴 숫자 가리기(app.model_adapter.mask_numbers). 학습 데이터도 같은 방식으로 가려 두었다.
- 리포트·점수 파일에는 id와 집계만 넣고 원문을 넣지 않는다.
"""

import asyncio
import csv
import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from app.analyzers import CompositeAnalyzer, RuleBasedAnalyzer
from app.contracts import RiskLevel
from app.model_adapter import ModelState, file_sha256, is_inside_repo, mask_numbers, prepare_model_text
from app.url_reputation import DisconnectedReputationProvider
from app.urls import UrlInputError, extract_urls

from .harness import DatasetError, Outcome, _analyze_one, _table, compute_binary_metrics, git_state, load_rows
from .model_training import (
    TrainingError, TrainingSet, _FixedScoreModel, choose_normal_threshold, choose_threshold, score_texts,
    select_training_rows,
)

# dev 출처 묶음. source 열의 앞 글자로 나눈다. "학습에 같은 출처가 있음"은 finetune 세트 기준이다.
SOURCE_FAMILIES = (
    ("KR-MOB", "KR-MOB v1 (학습에 v2 있음)"),
    ("LGAI", "LGAI (학습에 같은 출처 있음)"),
    ("공공데이터포털", "공공 안내 문자"),
    ("본인", "실제 받은 문자"),
    ("직접", "직접 작성"),
)
UNSEEN_FAMILY = "직접 작성"


class ExternalDataError(ValueError):
    """학습 세트 입력 오류. 메시지에 원문을 넣지 않는다."""


def model_input(content: str) -> str | None:
    try:
        spans = extract_urls(content).spans
    except UrlInputError:
        return None
    return mask_numbers(prepare_model_text(content, spans))


@dataclass
class ExternalSet:
    texts: list[str] = field(repr=False)
    labels: list[int]
    sources: list[str]
    skipped: int = 0
    sha256: str = ""
    name: str = ""


def load_external(path: Path) -> ExternalSet:
    data = ExternalSet([], [], [], sha256=file_sha256(path), name=path.name)
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if not {"text", "label", "source"} <= set(reader.fieldnames or ()):
            raise ExternalDataError("학습 세트에 text, label, source 열이 있어야 해요.")
        for row in reader:
            text = model_input(row["text"] or "")
            if not text or row["label"] not in ("0", "1"):
                data.skipped += 1
                continue
            data.texts.append(text)
            data.labels.append(int(row["label"]))
            data.sources.append(row["source"])
    if set(data.labels) != {0, 1}:
        raise ExternalDataError("학습 세트에 두 라벨이 모두 있어야 해요.")
    return data


def load_dev(path: Path) -> TrainingSet:
    rows = load_rows(path)
    dev = select_training_rows(rows, "binary")
    del rows  # test 행 원문을 더 들고 있지 않는다.
    if not dev.rows:
        raise DatasetError("비교할 dev 행이 없어요.")
    dev.texts = [mask_numbers(text) for text in dev.texts]
    return dev


def family(source: str) -> str:
    return next((name for prefix, name in SOURCE_FAMILIES if source.startswith(prefix)), "기타")


def crossfit_thresholds(scores: list[float], labels: list[int], groups: list[str], seed: int, n_splits: int):
    """행마다 (다른 fold에서 고른 임계값, 정상 임계값)과 fold 번호."""
    from sklearn.model_selection import StratifiedGroupKFold

    splitter = StratifiedGroupKFold(n_splits=n_splits, shuffle=True, random_state=seed)
    thresholds: list[float | None] = [None] * len(scores)
    normals: list[float | None] = [None] * len(scores)
    folds = [-1] * len(scores)
    for fold, (fit_idx, apply_idx) in enumerate(splitter.split(scores, labels, groups)):
        fit_scores, fit_labels = [scores[i] for i in fit_idx], [labels[i] for i in fit_idx]
        threshold = choose_threshold(fit_scores, fit_labels)
        normal = choose_normal_threshold(fit_scores, fit_labels, threshold)
        for i in apply_idx:
            thresholds[i], normals[i], folds[i] = threshold, normal, fold
    return thresholds, normals, folds


async def _combined(dev: TrainingSet, scores, thresholds, normals, version: str, timeout: float) -> list[Outcome]:
    rules = RuleBasedAnalyzer(DisconnectedReputationProvider("training_offline"))
    out = []
    for row, score, threshold, normal in zip(dev.rows, scores, thresholds, normals):
        model = _FixedScoreModel(score, threshold if threshold is not None else 2.0, version, normal)
        out.append(await _analyze_one(CompositeAnalyzer(rules, ModelState("loaded", model)), row, timeout))
    return out


async def _rules_only(dev: TrainingSet, timeout: float) -> list[Outcome]:
    rules = RuleBasedAnalyzer(DisconnectedReputationProvider("training_offline"))
    return [await _analyze_one(rules, row, timeout) for row in dev.rows]


def summarize(outcomes: list[Outcome]) -> dict:
    def one(group: list[Outcome]) -> dict:
        if not group:
            return {}
        m = compute_binary_metrics(group)
        normal = RiskLevel.NORMAL.value
        return {"rows": m.total, "scam_total": m.scam_total, "scam_warned": m.scam_warned,
                "scam_to_normal": m.confusion["scam"][normal], "legit_total": m.legit_total,
                "legit_flagged": m.legit_flagged, "legit_dangerous": m.legit_dangerous,
                "legit_to_normal": m.confusion["legit"][normal], "errors": m.errors}

    by_family = {}
    for outcome in outcomes:
        by_family.setdefault(family(outcome.row.source), []).append(outcome)
    return {"all": one(outcomes), "families": {name: one(group) for name, group in by_family.items()}}


def _val_auc(model, val: ExternalSet | None) -> float | None:
    if val is None:
        return None
    from sklearn.metrics import roc_auc_score
    return float(roc_auc_score(val.labels, score_texts(model, val.texts)))


@dataclass
class Candidate:
    name: str
    description: str
    factory: Callable[[int], object]
    # 모델 파일로 남길 때 쓰는 함수 (out_dir, model) -> manifest에 더할 dict. 없으면 점수만 남긴다.
    export: Callable[[Path, object], dict] | None = None
    config: dict = field(default_factory=dict)


def run_candidate(candidate: Candidate, train_set: ExternalSet, val_set: ExternalSet | None, dev: TrainingSet,
                  out_dir: Path, seed: int, n_splits: int, timeout: float = 5.0) -> dict:
    if is_inside_repo(out_dir):
        raise TrainingError("출력 폴더는 저장소 밖이어야 해요.")
    target = out_dir / candidate.name
    if (target / "result.json").exists():
        raise TrainingError("출력 폴더에 이미 결과가 있어요. 새 폴더를 지정해주세요.")
    target.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    model = candidate.factory(seed)
    if hasattr(model, "fit_with_validation") and val_set is not None:
        model.fit_with_validation(train_set.texts, train_set.labels, val_set.texts, val_set.labels)
    else:
        model.fit(train_set.texts, train_set.labels)
    train_seconds = time.perf_counter() - started
    dev_scores = score_texts(model, dev.texts)
    thresholds, normals, folds = crossfit_thresholds(dev_scores, dev.labels, dev.groups, seed, n_splits)
    combined = asyncio.run(_combined(dev, dev_scores, thresholds, normals, candidate.name, timeout))
    final_threshold = choose_threshold(dev_scores, dev.labels)
    final_normal = choose_normal_threshold(dev_scores, dev.labels, final_threshold)
    flagged = [t is not None and s >= t for s, t in zip(dev_scores, thresholds)]
    result = {
        "name": candidate.name, "description": candidate.description, "config": candidate.config,
        "train_seconds": round(train_seconds, 1), "val_auc": _val_auc(model, val_set),
        "model_alone": {"scam_signal": sum(f and y == 1 for f, y in zip(flagged, dev.labels)),
                        "legit_signal": sum(f and y == 0 for f, y in zip(flagged, dev.labels)),
                        "scam_total": sum(dev.labels), "legit_total": len(dev.labels) - sum(dev.labels)},
        "fold_thresholds": sorted({(f, t, n) for f, t, n in zip(folds, thresholds, normals)}),
        "final_threshold": final_threshold, "final_normal_threshold": final_normal,
        "combined": summarize(combined),
    }
    with (target / "dev-scores.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "label", "score", "fold", "predicted"])
        for row, label, score, fold, outcome in zip(dev.rows, dev.labels, dev_scores, folds, combined):
            writer.writerow([row.id, label, f"{score:.6f}", fold, outcome.predicted])
    if candidate.export is not None:
        result["export"] = candidate.export(target, model)
    (target / "result.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return result


def _rate(n: int, d: int) -> str:
    return f"{n}/{d} ({n / d:.1%})" if d else "-"


def _eligible(result: dict, rules: dict) -> bool:
    c = result["combined"]["all"]
    return c["scam_to_normal"] == 0 and c["legit_flagged"] <= rules["legit_flagged"] and c["errors"] == 0


def rank(results: list[dict], rules: dict) -> list[dict]:
    """선택 기준(임시, 사용자 승인 2026-11-24): 정상 오탐이 rules보다 늘지 않고 사기 → 정상 0건인 후보 중
    dev 사기 경고가 가장 많은 것. 같으면 직접 작성(학습에 없는 출처) 사기 경고, 그다음 학습 시간이 짧은 것."""
    def key(r):
        fam = r["combined"]["families"].get(UNSEEN_FAMILY, {})
        return (not _eligible(r, rules), -r["combined"]["all"]["scam_warned"], -fam.get("scam_warned", 0),
                r["train_seconds"])
    return sorted(results, key=key)


def render_report(results: list[dict], rules: dict, meta: dict) -> str:
    ranked = rank(results, rules["all"])
    lines = [
        "# PtoS 학습 전용 데이터 후보 비교 (dev, cross-fitted 임계값)", "",
        *_table(["항목", "값"], [[k, v] for k, v in meta.items()]), "",
        "원문은 넣지 않는다. **dev 문자 입력 약 500건 규모의 비교이며 탐지 성능 주장이 아니다.** 임계값·선택 기준은 임시다.",
        "임계값은 다른 fold에서 고른 값을 적용했으므로, 고른 행에서는 0건이던 정상 신호가 여기서는 나올 수 있다.",
        "dev는 학습에 쓰지 않았다. 다만 규칙 보강과 이전 모델 학습에 쓴 행이라 rules 수치는 부풀려져 있다.", "",
        "## 종합 (rules+후보, dev 전체)", "",
    ]
    r = rules["all"]
    rows = [["(rules만)", "-", _rate(r["scam_warned"], r["scam_total"]), _rate(r["legit_flagged"], r["legit_total"]),
             r["scam_to_normal"], _rate(r["legit_to_normal"], r["legit_total"]), "-", "-", "-"]]
    for x in ranked:
        c, m = x["combined"]["all"], x["model_alone"]
        rows.append([x["name"] + ("" if _eligible(x, r) else " (기준 미달)"),
                     f"{x['val_auc']:.3f}" if x["val_auc"] is not None else "-",
                     _rate(c["scam_warned"], c["scam_total"]), _rate(c["legit_flagged"], c["legit_total"]),
                     c["scam_to_normal"], _rate(c["legit_to_normal"], c["legit_total"]),
                     f"{m['scam_signal']} / {m['legit_signal']}",
                     "N/A" if x["final_threshold"] is None else f"{x['final_threshold']:.5f}", f"{x['train_seconds']:.0f}s"])
    lines += _table(["후보", "val AUC(부풀려짐)", "사기 경고", "정상 오탐", "사기→정상", "정상→정상",
                     "모델 단독 신호 사기/정상", "최종 임계값", "학습 시간"], rows)
    lines += ["", "## 출처별 사기 경고 / 정상 오탐", ""]
    names = [name for _, name in SOURCE_FAMILIES]
    header = ["후보", *names]

    def cell(f: dict) -> str:
        if not f:
            return "-"
        parts = []
        if f["scam_total"]:
            parts.append(f"사기 {f['scam_warned']}/{f['scam_total']}")
        if f["legit_total"]:
            parts.append(f"오탐 {f['legit_flagged']}/{f['legit_total']}")
        return ", ".join(parts)

    lines += _table(header, [["(rules만)", *(cell(rules["families"].get(n, {})) for n in names)],
                             *([x["name"], *(cell(x["combined"]["families"].get(n, {})) for n in names)] for x in ranked)])
    lines += ["", "- 선택 기준(임시): 정상 오탐이 rules보다 늘지 않고 사기 → 정상 0건인 후보 중 사기 경고 최다, "
              "같으면 직접 작성 출처 사기 경고, 그다음 학습 시간.", ""]
    for x in ranked:
        lines += [f"### {x['name']}", "", f"- {x['description']}",
                  "- fold별 임계값(fold, 신호, 정상): " + ", ".join(
                      f"({f}, {'N/A' if t is None else f'{t:.5f}'}, {'N/A' if n is None else f'{n:.5f}'})"
                      for f, t, n in x["fold_thresholds"]), ""]
    return "\n".join(lines)


def compare_external(train_path: Path, val_path: Path | None, data_path: Path, out_dir: Path,
                     candidates: list[Candidate], seed: int, n_splits: int) -> str:
    train_set, val_set = load_external(train_path), (load_external(val_path) if val_path else None)
    dev = load_dev(data_path)
    rules = summarize(asyncio.run(_rules_only(dev, 5.0)))
    results = []
    for candidate in candidates:
        print(f"[{datetime.now():%H:%M:%S}] 학습 시작: {candidate.name}", flush=True)
        results.append(run_candidate(candidate, train_set, val_set, dev, out_dir, seed, n_splits))
        print(f"[{datetime.now():%H:%M:%S}] 끝: {candidate.name} ({results[-1]['train_seconds']:.0f}s)", flush=True)
    commit, dirty = git_state(Path(__file__).resolve().parents[2])
    meta = {"학습 세트": f"{train_set.name} {len(train_set.labels)}행 (사기 {sum(train_set.labels)}), 건너뜀 {train_set.skipped}, "
                       f"SHA-256 `{train_set.sha256[:16]}…`",
            "검증 세트": f"{val_set.name} {len(val_set.labels)}행" if val_set else "없음",
            "dev": f"{data_path.name} {len(dev.rows)}행 (사기 {sum(dev.labels)}), campaign {len(set(dev.groups))}개, "
                   f"SHA-256 `{file_sha256(data_path)[:16]}…`, test 행 {dev.test_rows_dropped}건 버림",
            "시드 / fold": f"{seed} / {n_splits}", "코드 커밋": f"`{commit}`" + (" (작업 트리 변경 있음)" if dirty else ""),
            "실행 시각": datetime.now().astimezone().isoformat(timespec="seconds")}
    return render_report(results, rules, meta)
