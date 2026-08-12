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

    def _score(self, profile: BackendProfile) -> float:
        return (
            self.latency_weight * profile.mean_latency_ms
            + self.cost_weight * profile.cost_per_1k_tokens
            - self.throughput_weight * profile.output_tokens_per_second
        )

    def choose(self) -> tuple[InferenceAdapter, SelectionDecision]:
        selected = min(self.profiles, key=self._score)
        score = self._score(selected)
        return selected.adapter, SelectionDecision(
            adapter=selected.adapter.name,
            score=round(score, 6),
            reason="lowest weighted latency/cost score with throughput benefit",
        )

    def infer(self, prompt: str, *, max_tokens: int) -> tuple[InferenceResponse, SelectionDecision]:
        adapter, decision = self.choose()
        return adapter.infer(prompt, max_tokens=max_tokens), decision
