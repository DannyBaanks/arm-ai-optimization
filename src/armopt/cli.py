"""CLI benchmark runner for the backend-neutral harness."""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

from .contracts import InferenceAdapter, InferenceResponse, Workload
from .evidence import write_evidence
from .http_adapter import HttpAdapter, HttpAdapterConfig
from .runner import compare_modes, run_benchmark
from .workload import load_workload


class DemoAdapter:
    name = "demo-adapter"

    def infer(self, prompt: str, *, max_tokens: int) -> InferenceResponse:
        # Deterministic adapter used only to validate the harness wiring.
        output = prompt[:max_tokens]
        time.sleep(0.001)
        return InferenceResponse(output, len(prompt.split()), len(output.split()))


def _build_adapter(args: argparse.Namespace) -> InferenceAdapter:
    if args.adapter == "demo":
        return DemoAdapter()
    if not args.http_url or not args.http_model:
        raise SystemExit("--http-url and --http-model are required for --adapter http")
    return HttpAdapter(HttpAdapterConfig(
        url=args.http_url,
        model=args.http_model,
        name=f"http:{args.http_backend}:{args.http_model}",
        backend=args.http_backend,
        num_thread=args.http_num_thread,
    ))


def _build_workload(args: argparse.Namespace) -> Workload:
    if args.workload_file is not None:
        return load_workload(args.workload_file, max_tokens=args.max_tokens)
    return Workload(
        prompts=[f"benchmark prompt {index}" for index in range(args.requests)],
        max_tokens=args.max_tokens,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true", help="alias for --adapter demo")
    parser.add_argument("--adapter", choices=("demo", "http"), default="demo")
    parser.add_argument("--http-url", default=None,
                         help="base URL of an Ollama-compatible runtime, e.g. http://localhost:11434")
    parser.add_argument("--http-model", default=None,
                         help="model name (Ollama) or a label (llama-server; not sent to the server)")
    parser.add_argument("--http-backend", choices=("ollama", "llama_server"), default="ollama")
    parser.add_argument("--http-num-thread", type=int, default=None,
                         help="CPU threads per request; set to cores // workers to avoid "
                              "concurrent requests oversubscribing the same cores")
    parser.add_argument("--workload-file", type=Path, default=None,
                         help="JSON/JSONL file of prompts; overrides --requests")
    parser.add_argument("--requests", type=int, default=16,
                         help="synthetic prompt count, ignored if --workload-file is set")
    parser.add_argument("--max-tokens", type=int, default=64)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--mode", choices=("sequential", "dataflow", "both"), default="both")
    parser.add_argument("--repeats", type=int, default=1,
                         help="repeat each mode this many times and report the median")
    parser.add_argument("--warmup", type=int, default=1,
                         help="untimed requests before the first repeat of each mode")
    parser.add_argument("--evidence", type=Path, default=None,
                         help="write a signed evidence JSON here, e.g. evidence/run.json")
    parser.add_argument("--workload-id", default="inline-demo")
    args = parser.parse_args()
    if args.demo:
        args.adapter = "demo"
    if args.requests < 1:
        parser.error("--requests must be positive")

    adapter = _build_adapter(args)
    workload = _build_workload(args)

    if args.mode == "both":
        result = compare_modes(
            adapter, workload,
            workers=args.workers, repeats=args.repeats, warmup_requests=args.warmup,
        )
    else:
        result = run_benchmark(
            adapter, workload,
            workers=args.workers, mode=args.mode, warmup_requests=args.warmup,
        ).to_dict()
    print(json.dumps(result, indent=2))

    if args.evidence is not None:
        args.evidence.parent.mkdir(parents=True, exist_ok=True)
        write_evidence(
            args.evidence,
            results=result,
            workload_id=args.workload_id,
            adapter=adapter.name,
        )
        print(f"evidence written to {args.evidence}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
