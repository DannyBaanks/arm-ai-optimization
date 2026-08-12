"""Pick the best-measured backend from recorded benchmark evidence.

This is what makes the scheduler part of the real pipeline instead of an
isolated feature exercised only by synthetic profiles in tests: it reads
the same signed evidence JSON `armopt.cli --evidence` writes, builds a
`BackendProfile` per file from the *measured* dataflow figures, and asks
`CostLatencyScheduler` which one it would actually deploy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .contracts import InferenceResponse
from .scheduler import BackendProfile, CostLatencyScheduler


class _EvidenceAdapter:
    """Carries only the name a profile was measured under. Selecting among
    prior evidence is a recommendation step, not a live call, so there is
    no real runtime behind this -- calling infer() is a programming error."""

    def __init__(self, name: str) -> None:
        self.name = name

    def infer(self, prompt: str, *, max_tokens: int) -> InferenceResponse:
        raise NotImplementedError(
            f"{self.name!r} is a recorded-evidence profile, not a live adapter"
        )


def profile_from_evidence(path: Path, *, cost_per_1k_tokens: float = 0.0) -> BackendProfile:
    payload = json.loads(path.read_text(encoding="utf-8"))
    results = payload["results"]
    # Prefer the dataflow (concurrent) figures when present: that's the
    # execution strategy this harness measured as the one to deploy under.
    measured = results["dataflow"] if "dataflow" in results else results
    return BackendProfile(
        adapter=_EvidenceAdapter(payload["adapter"]),
        mean_latency_ms=measured["mean_latency_ms"],
        output_tokens_per_second=measured["tokens_per_second"],
        cost_per_1k_tokens=cost_per_1k_tokens,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", action="append", required=True, metavar="PATH",
                         help="an evidence JSON written by armopt.cli --evidence; repeatable")
    parser.add_argument("--cost-per-1k-tokens", action="append", type=float, default=[],
                         metavar="COST",
                         help="cost paired positionally with --evidence; missing entries "
                              "default to 0.0 (local/free runtimes)")
    parser.add_argument("--latency-weight", type=float, default=1.0)
    parser.add_argument("--cost-weight", type=float, default=1.0)
    parser.add_argument("--throughput-weight", type=float, default=1.0)
    args = parser.parse_args()

    costs = args.cost_per_1k_tokens + [0.0] * (len(args.evidence) - len(args.cost_per_1k_tokens))
    profiles = [
        profile_from_evidence(Path(path), cost_per_1k_tokens=cost)
        for path, cost in zip(args.evidence, costs)
    ]
    scheduler = CostLatencyScheduler(
        profiles,
        latency_weight=args.latency_weight,
        cost_weight=args.cost_weight,
        throughput_weight=args.throughput_weight,
    )
    _, decision = scheduler.choose()
    print(json.dumps({
        "candidates": [
            {
                "adapter": profile.adapter.name,
                "mean_latency_ms": profile.mean_latency_ms,
                "output_tokens_per_second": profile.output_tokens_per_second,
                "cost_per_1k_tokens": profile.cost_per_1k_tokens,
            }
            for profile in profiles
        ],
        "selected": decision.adapter,
        "score": decision.score,
        "reason": decision.reason,
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
