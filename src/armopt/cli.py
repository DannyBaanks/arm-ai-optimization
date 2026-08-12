"""CLI smoke benchmark for the backend-neutral harness."""
from __future__ import annotations

import argparse
import json
import time

from .contracts import InferenceResponse, Workload
from .runner import compare_modes, run_benchmark


class DemoAdapter:
    name = "demo-adapter"

    def infer(self, prompt: str, *, max_tokens: int) -> InferenceResponse:
        # Deterministic adapter used only to validate the harness wiring.
        output = prompt[:max_tokens]
        time.sleep(0.001)
        return InferenceResponse(output, len(prompt.split()), len(output.split()))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo", action="store_true")
    parser.add_argument("--requests", type=int, default=16)
    parser.add_argument("--workers", type=int, default=1)
    parser.add_argument("--mode", choices=("sequential", "dataflow", "both"), default="both")
    args = parser.parse_args()
    if not args.demo:
        parser.error("the initial CLI exposes only --demo")
    if args.requests < 1:
        parser.error("--requests must be positive")

    workload = Workload(
        prompts=[f"benchmark prompt {index}" for index in range(args.requests)]
    )
    adapter = DemoAdapter()
    if args.mode == "both":
        result = compare_modes(adapter, workload, workers=args.workers)
    else:
        result = run_benchmark(
            adapter,
            workload,
            workers=args.workers,
            mode=args.mode,
        ).to_dict()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
