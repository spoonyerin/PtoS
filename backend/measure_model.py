"""Run from backend: python measure_model.py [--model-dir <폴더>] [--data <CSV>] [--output <md>].

모델 로드 시간·메모리와 요청당 추론 시간을 이 컴퓨터에서 간단히 잰다. 성능 보장이나 제품 목표(5초) 검증이 아니다.
--data를 주면 split=dev의 text 행만 쓰고 test 행은 쓰지 않는다. 출력에는 집계만 넣고 원문을 넣지 않는다.
"""
import argparse
import asyncio
import csv
import math
import os
import platform
import sys
import time
import tracemalloc
from pathlib import Path

from pydantic import ValidationError

from app.analyzers import CompositeAnalyzer, RuleBasedAnalyzer
from app.contracts import MAX_CONTENT_LENGTH, AnalysisInput
from app.model_adapter import MODEL_PATH_ENV, ModelLoadError, ModelState, load_model, prepare_model_text, read_manifest
from app.url_reputation import DisconnectedReputationProvider
from app.urls import extract_urls

# 저장소에 둘 수 있는 고정 가짜 문장. 실제 수신 문자가 아니다.
FIXED_SAMPLES = {
    "짧은 문장": "[가짜 측정 문장] 내일 오후 두 시에 도서관에서 만나요.",
    "보통 문장": "[가짜 측정 문장] 가짜기관입니다. 미납 요금이 있어 오늘까지 아래 주소에서 확인해주세요. https://example.invalid/pay " * 3,
    "최대 길이": ("[가짜 측정 문장] 택배 주소를 확인해주세요. " * 600)[:MAX_CONTENT_LENGTH],
}


def rss_bytes() -> int | None:
    """현재 프로세스 상주 메모리(바이트). 확인할 수 없으면 None."""
    if sys.platform == "win32":
        import ctypes
        from ctypes import wintypes

        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD),
                        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
                        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
                        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
                        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

        counters = Counters()
        counters.cb = ctypes.sizeof(Counters)
        psapi = ctypes.WinDLL("psapi")
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        if psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
            return int(counters.WorkingSetSize)
        return None
    try:
        with open("/proc/self/statm", encoding="ascii") as handle:
            return int(handle.read().split()[1]) * os.sysconf("SC_PAGE_SIZE")
    except (OSError, ValueError, IndexError):
        return None


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def dev_inputs(data_path: Path) -> tuple[list[AnalysisInput], int]:
    from evaluation.harness import load_rows

    rows = [row for row in load_rows(data_path) if row.split == "dev" and row.input_type == "text"]
    inputs, skipped = [], 0
    for row in rows:
        try:
            inputs.append(AnalysisInput(input_type="text", content=row.content))
        except ValidationError:
            skipped += 1
    return inputs, skipped


def _time_ms(call) -> float:
    start = time.perf_counter()
    call()
    return (time.perf_counter() - start) * 1000


def measure(model_dir: Path, data_path: Path | None = None, repeat: int = 20) -> dict:
    rss_before = rss_bytes()
    start = time.perf_counter()
    model = load_model(model_dir)
    load_seconds = time.perf_counter() - start
    rss_after = rss_bytes()
    # tracemalloc은 로드를 느리게 하므로 시간과 따로, 두 번째 로드에서 Python 할당 최대치를 잰다.
    tracemalloc.start()
    load_model(model_dir)
    _, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    groups = {name: [AnalysisInput(input_type="text", content=text)] for name, text in FIXED_SAMPLES.items()}
    skipped = 0
    if data_path is not None:
        groups["dev text 행"], skipped = dev_inputs(data_path)
    rules = RuleBasedAnalyzer(DisconnectedReputationProvider("measure_offline"))
    composite = CompositeAnalyzer(rules, ModelState("loaded", model), model_timeout=60.0)
    loop = asyncio.new_event_loop()
    try:
        model.score("워밍업")
        loop.run_until_complete(composite.analyze(groups["짧은 문장"][0]))
        results = {}
        for name, inputs in groups.items():
            prepared = [prepare_model_text(data.content, extract_urls(data.content).spans) for data in inputs]
            timings = {"model.score": [], "rules": [], "rules+model": []}
            for _ in range(repeat):
                for data, text in zip(inputs, prepared):
                    timings["model.score"].append(_time_ms(lambda: model.score(text)))
                    timings["rules"].append(_time_ms(lambda: loop.run_until_complete(rules.analyze(data))))
                    timings["rules+model"].append(_time_ms(lambda: loop.run_until_complete(composite.analyze(data))))
            results[name] = {"inputs": len(inputs), **{
                key: {"p50": percentile(v, 0.5), "p95": percentile(v, 0.95), "max": max(v)} for key, v in timings.items() if v}}
    finally:
        loop.close()

    import sklearn
    manifest = read_manifest(model_dir)
    return {
        "environment": {"python": platform.python_version(), "platform": platform.platform(), "cpu_count": os.cpu_count(),
                        "scikit-learn": sklearn.__version__},
        "model_version": model.version, "model_sha256": manifest["model_sha256"],
        "model_file_bytes": (model_dir / manifest["model_file"]).stat().st_size,
        "load_seconds": load_seconds, "traced_peak_bytes": traced_peak,
        "rss_before_bytes": rss_before, "rss_after_bytes": rss_after,
        "repeat": repeat, "dev_inputs_skipped": skipped, "latency_ms": results,
    }


def _mib(value: int | None) -> str:
    return "확인 불가" if value is None else f"{value / (1 << 20):.1f} MiB"


def render(result: dict) -> str:
    env = result["environment"]
    rss_delta = (None if result["rss_before_bytes"] is None or result["rss_after_bytes"] is None
                 else result["rss_after_bytes"] - result["rss_before_bytes"])
    lines = [
        "# PtoS 모델 지연·메모리 측정", "",
        "이 컴퓨터에서 한 번 잰 값이다. 성능 보장이나 제품 목표(텍스트 5초) 검증이 아니다. 원문은 넣지 않는다.", "",
        f"- 환경: Python {env['python']}, {env['platform']}, CPU {env['cpu_count']}개, scikit-learn {env['scikit-learn']}",
        f"- 모델: {result['model_version']} (`{result['model_sha256']}`), 파일 {_mib(result['model_file_bytes'])}",
        f"- 로드 시간: {result['load_seconds'] * 1000:.1f} ms (프로세스 첫 로드, import 포함)",
        f"- 로드 중 Python 할당 최대치(tracemalloc): {_mib(result['traced_peak_bytes'])}",
        f"- 상주 메모리: 로드 전 {_mib(result['rss_before_bytes'])} → 로드 후 {_mib(result['rss_after_bytes'])}"
        + ("" if rss_delta is None else f" (증가 {_mib(rss_delta)})"),
        f"- 반복: 입력마다 {result['repeat']}회. rules·rules+model은 URL 평판 미연결 상태의 분석기 전체 시간이다.",
    ]
    if result["dev_inputs_skipped"]:
        lines.append(f"- 입력 검증을 통과하지 못해 뺀 dev 행: {result['dev_inputs_skipped']}건")
    lines += ["", "| 입력 묶음 | 입력 수 | 단계 | p50 (ms) | p95 (ms) | 최대 (ms) |", "| --- | --- | --- | --- | --- | --- |"]
    for name, group in result["latency_ms"].items():
        for key in ("model.score", "rules", "rules+model"):
            if key in group:
                stats = group[key]
                lines.append(f"| {name} | {group['inputs']} | {key} | {stats['p50']:.2f} | {stats['p95']:.2f} | {stats['max']:.2f} |")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="모델 로드·추론 시간과 메모리를 간단히 잰다. 원문은 출력하지 않는다.")
    parser.add_argument("--model-dir", type=Path, default=None, help=f"모델 폴더 (없으면 {MODEL_PATH_ENV})")
    parser.add_argument("--data", type=Path, help="평가 CSV (dev text 행만 사용, 선택)")
    parser.add_argument("--repeat", type=int, default=20)
    parser.add_argument("--output", type=Path, help="Markdown 저장 경로 (없으면 표준 출력)")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    model_dir = args.model_dir or (Path(os.environ[MODEL_PATH_ENV]) if os.environ.get(MODEL_PATH_ENV, "").strip() else None)
    if model_dir is None:
        print(f"모델 폴더가 필요해요. --model-dir 또는 {MODEL_PATH_ENV}를 지정해주세요.", file=sys.stderr)
        return 2
    from evaluation.harness import DatasetError
    try:
        report = render(measure(model_dir, args.data, args.repeat))
    except ModelLoadError as error:
        print(f"모델을 불러오지 못했어요 ({error.code}).", file=sys.stderr)
        return 1
    except DatasetError as error:
        print(f"평가셋 형식 오류: {error}", file=sys.stderr)
        return 1
    except (OSError, UnicodeDecodeError, csv.Error) as error:
        # 경로나 셀 값이 메시지에 섞일 수 있어 오류 종류만 알린다.
        print(f"평가 CSV를 읽지 못했어요 ({error.__class__.__name__}).", file=sys.stderr)
        return 1
    if args.output:
        args.output.write_text(report + "\n", encoding="utf-8")
    else:
        print(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
