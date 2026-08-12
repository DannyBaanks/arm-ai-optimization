"""Small backend-neutral contracts used by the benchmark harness."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, Sequence


@dataclass(frozen=True, slots=True)
class InferenceResponse:
    text: str
    input_tokens: int
    output_tokens: int


class InferenceAdapter(Protocol):
    """Adapter implemented by an AI runtime or remote inference service."""

    name: str

    def infer(self, prompt: str, *, max_tokens: int) -> InferenceResponse:
        ...


@dataclass(frozen=True, slots=True)
class Workload:
    prompts: Sequence[str]
    max_tokens: int = 64

    def __post_init__(self) -> None:
        if not self.prompts:
            raise ValueError("workload must contain at least one prompt")
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be positive")
