"""Baseline and parallel benchmark execution with auditable metrics."""
from __future__ import annotations

import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Literal

from .contracts import InferenceAdapter, Workload

ExecutionMode = Literal["sequential", "dataflow"]


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    adapter: str
    mode: ExecutionMode
    requests: int
    workers: int
    wall_ms: float
    mean_latency_ms: float
    p95_latency_ms: float
    output_tokens: int
    tokens_per_second: float

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


class DataflowSession:
    """Reusable execution session for repeated Dataflow batches."""

    def __init__(self, workers: int) -> None:
        if workers < 1:
            raise ValueError("workers must be positive")
        self.workers = workers
        self._executor = ThreadPoolExecutor(max_workers=workers)

    def map(self, function, values):
        return list(self._executor.map(function, values))

    def close(self) -> None:
        self._executor.shutdown(wait=True)

    def __enter__(self) -> "DataflowSession":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()


def _percentile(values: list[float], percentile: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, round((len(ordered) - 1) * percentile))
    return ordered[index]


def run_benchmark(
    adapter: InferenceAdapter,
    workload: Workload,
    *,
    workers: int = 1,
    mode: ExecutionMode = "sequential",
    session: DataflowSession | None = None,
    warmup_requests: int = 0,
) -> BenchmarkResult:
    """Run a workload and return latency/throughput metrics for this pass.

    ``warmup_requests`` calls happen first and are excluded from every
    metric below -- they exist to absorb model-load/cache-cold latency so
    the timed pass reflects steady-state performance, not first-token cost.
    """
    if workers < 1:
        raise ValueError("workers must be positive")
    if mode not in ("sequential", "dataflow"):
        raise ValueError(f"unsupported execution mode: {mode}")
    if warmup_requests < 0:
        raise ValueError("warmup_requests must not be negative")

    prompts = list(workload.prompts)
    latencies: list[float] = []
    output_tokens = 0

    def execute(prompt: str) -> tuple[float, int]:
        started = time.perf_counter()
        response = adapter.infer(prompt, max_tokens=workload.max_tokens)
        elapsed_ms = (time.perf_counter() - started) * 1000
        return elapsed_ms, response.output_tokens

    for _ in range(warmup_requests):
        adapter.infer(prompts[0], max_tokens=workload.max_tokens)

    started = time.perf_counter()
    if mode == "sequential":
        results = [execute(prompt) for prompt in prompts]
        actual_mode: ExecutionMode = "sequential"
    else:
        if session is None:
            with DataflowSession(workers) as pool:
                results = pool.map(execute, prompts)
        else:
            results = session.map(execute, prompts)
        actual_mode = "dataflow"
    wall_ms = (time.perf_counter() - started) * 1000

    for latency_ms, tokens in results:
        latencies.append(latency_ms)
        output_tokens += tokens
    wall_seconds = wall_ms / 1000
    return BenchmarkResult(
        adapter=adapter.name,
        mode=actual_mode,
        requests=len(prompts),
        workers=workers,
        wall_ms=round(wall_ms, 3),
        mean_latency_ms=round(statistics.mean(latencies), 3),
        p95_latency_ms=round(_percentile(latencies, 0.95), 3),
        output_tokens=output_tokens,
        tokens_per_second=round(output_tokens / wall_seconds, 3) if wall_seconds else 0,
    )


def _median_result(results: list[BenchmarkResult]) -> BenchmarkResult:
    """Collapse repeated runs into their median, so one lucky/unlucky pass
    can't decide the headline number."""
    first = results[0]
    return BenchmarkResult(
        adapter=first.adapter,
        mode=first.mode,
        requests=first.requests,
        workers=first.workers,
        wall_ms=round(statistics.median(r.wall_ms for r in results), 3),
        mean_latency_ms=round(statistics.median(r.mean_latency_ms for r in results), 3),
        p95_latency_ms=round(statistics.median(r.p95_latency_ms for r in results), 3),
        output_tokens=results[-1].output_tokens,
        tokens_per_second=round(statistics.median(r.tokens_per_second for r in results), 3),
    )


def compare_modes(
    adapter: InferenceAdapter,
    workload: Workload,
    *,
    workers: int = 1,
    repeats: int = 1,
    warmup_requests: int = 1,
) -> dict[str, object]:
    """Run the identical workload through baseline and persistent Dataflow.

    Each mode runs ``repeats`` times (with ``warmup_requests`` untimed calls
    before the first repeat only) and reports the median across repeats.
    This measures the benefit of the execution *strategy* -- reusing a
    persistent worker pool instead of running requests one at a time -- for
    whatever adapter is plugged in. It is not a claim about the adapter's
    own internal optimizations.
    """
    if repeats < 1:
        raise ValueError("repeats must be positive")

    baseline_runs = [
        run_benchmark(
            adapter, workload, workers=1, mode="sequential",
            warmup_requests=warmup_requests if index == 0 else 0,
        )
        for index in range(repeats)
    ]
    with DataflowSession(workers) as session:
        dataflow_runs = [
            run_benchmark(
                adapter, workload, workers=workers, mode="dataflow", session=session,
                warmup_requests=warmup_requests if index == 0 else 0,
            )
            for index in range(repeats)
        ]

    baseline = _median_result(baseline_runs)
    dataflow = _median_result(dataflow_runs)
    speedup = baseline.wall_ms / dataflow.wall_ms if dataflow.wall_ms else 0.0
    return {
        "baseline": baseline.to_dict(),
        "dataflow": dataflow.to_dict(),
        "speedup_wall": round(speedup, 3),
        "repeats": repeats,
    }
