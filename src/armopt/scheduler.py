"""Backend scheduler based on measured latency, throughput, and cost."""
from __future__ import annotations

from dataclasses import dataclass

from .contracts import InferenceAdapter, InferenceResponse


@dataclass(frozen=True, slots=True)
class BackendProfile:
    adapter: InferenceAdapter
    mean_latency_ms: float
    output_tokens_per_second: float
    cost_per_1k_tokens: float

    def __post_init__(self) -> None:
        if self.mean_latency_ms < 0:
            raise ValueError("mean_latency_ms must not be negative")
        if self.output_tokens_per_second <= 0:
            raise ValueError("output_tokens_per_second must be positive")
        if self.cost_per_1k_tokens < 0:
            raise ValueError("cost_per_1k_tokens must not be negative")


@dataclass(frozen=True, slots=True)
class SelectionDecision:
    adapter: str
    score: float
    reason: str


class CostLatencyScheduler:
    """Choose among opaque adapters using externally measured profiles."""

    def __init__(self, profiles: list[BackendProfile], *, latency_weight: float = 1.0,
                 cost_weight: float = 1.0, throughput_weight: float = 1.0) -> None:
        if not profiles:
            raise ValueError("at least one backend profile is required")
        if min(latency_weight, cost_weight, throughput_weight) < 0:
            raise ValueError("scheduler weights must not be negative")
        self.profiles = profiles
        self.latency_weight = latency_weight
        self.cost_weight = cost_weight
        self.throughput_weight = throughput_weight

    @staticmethod
    def _normalized(value: float, values: list[float]) -> float:
        """Min-max normalize to [0, 1] across the candidate set.

        Raw latency (ms), cost (dollars), and throughput (tokens/s) live on
        unrelated scales -- summing them directly lets whichever metric
        happens to have the largest raw magnitude dominate the score
        regardless of the weights. Normalizing relative to the other
        candidates being compared makes the weights mean what they claim to.
        """
        low, high = min(values), max(values)
        if high == low:
            return 0.0
        return (value - low) / (high - low)

    def _score(self, profile: BackendProfile) -> float:
        latencies = [p.mean_latency_ms for p in self.profiles]
        costs = [p.cost_per_1k_tokens for p in self.profiles]
        throughputs = [p.output_tokens_per_second for p in self.profiles]
        return (
            self.latency_weight * self._normalized(profile.mean_latency_ms, latencies)
            + self.cost_weight * self._normalized(profile.cost_per_1k_tokens, costs)
            - self.throughput_weight * self._normalized(profile.output_tokens_per_second, throughputs)
        )

    def choose(self) -> tuple[InferenceAdapter, SelectionDecision]:
        selected = min(self.profiles, key=self._score)
        score = self._score(selected)
        return selected.adapter, SelectionDecision(
            adapter=selected.adapter.name,
            score=round(score, 6),
            reason="lowest weighted, normalized latency/cost score with throughput benefit",
        )

    def infer(self, prompt: str, *, max_tokens: int) -> tuple[InferenceResponse, SelectionDecision]:
        adapter, decision = self.choose()
        return adapter.infer(prompt, max_tokens=max_tokens), decision
