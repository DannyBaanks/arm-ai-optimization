"""HTTP adapter for interchangeable inference runtimes.

Targets Ollama's ``/api/generate`` contract by default (the runtime this
harness was validated against), but any HTTP runtime that accepts a JSON
POST and returns JSON can be reached by pointing ``url`` at it and adapting
``_build_payload``/``_parse_response`` below -- the adapter itself carries
no host, port, or model assumption; those are supplied by the caller
through ``HttpAdapterConfig``, exactly like ``JsonlAdapter.command``.

Unlike ``JsonlAdapter`` (one persistent process, one stdin/stdout pipe,
serialized behind a lock), each call here opens its own HTTP request and
holds no adapter-side lock. Concurrent callers therefore reach the runtime
concurrently -- ``ThreadPoolExecutor`` workers overlap in the runtime
itself, not just in Python. Any serialization from that point on is the
runtime's own concurrency limit (e.g. Ollama's ``OLLAMA_NUM_PARALLEL``),
not an artifact of this adapter.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass

from .contracts import InferenceResponse


@dataclass(frozen=True, slots=True)
class HttpAdapterConfig:
    url: str
    model: str
    name: str = "http-runtime"
    timeout_s: float = 60.0
    num_thread: int | None = None
    """CPU threads Ollama uses per request. Left unset, Ollama defaults to
    ~all available cores *per request* -- fine for one request at a time,
    but concurrent callers then oversubscribe the same cores against each
    other instead of getting real parallelism. Set this to roughly
    cpu_count // workers so N concurrent requests actually divide the
    machine instead of fighting over it."""

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("url must not be empty")
        if not self.model:
            raise ValueError("model must not be empty")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if self.num_thread is not None and self.num_thread < 1:
            raise ValueError("num_thread must be positive")


class HttpAdapter:
    """Talk to an Ollama-compatible ``/api/generate`` endpoint over HTTP."""

    def __init__(self, config: HttpAdapterConfig) -> None:
        self.name = config.name
        self._endpoint = config.url.rstrip("/") + "/api/generate"
        self._model = config.model
        self._timeout_s = config.timeout_s
        self._num_thread = config.num_thread

    def infer(self, prompt: str, *, max_tokens: int) -> InferenceResponse:
        options: dict[str, int] = {"num_predict": max_tokens}
        if self._num_thread is not None:
            options["num_thread"] = self._num_thread
        payload = json.dumps({
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": options,
        }).encode("utf-8")
        request = urllib.request.Request(
            self._endpoint,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                raw = response.read()
        except urllib.error.URLError as exc:
            raise RuntimeError(f"http runtime request to {self._endpoint} failed: {exc}") from exc

        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"http runtime returned non-JSON body: {raw[:200]!r}") from exc
        if "response" not in value:
            raise RuntimeError(f"http runtime returned an unexpected payload: {raw[:200]!r}")

        return InferenceResponse(
            text=str(value.get("response", "")),
            input_tokens=int(value.get("prompt_eval_count", 0)),
            output_tokens=int(value.get("eval_count", 0)),
        )
