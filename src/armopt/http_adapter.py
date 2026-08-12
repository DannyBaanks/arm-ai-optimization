"""HTTP adapter for interchangeable inference runtimes.

Supports two wire formats behind the same ``InferenceAdapter`` protocol:
Ollama's ``/api/generate`` (default) and llama.cpp's ``llama-server``
``/completion``. Neither host, port, nor model is assumed by the adapter
itself -- those are supplied by the caller through ``HttpAdapterConfig``,
exactly like ``JsonlAdapter.command``.

Unlike ``JsonlAdapter`` (one persistent process, one stdin/stdout pipe,
serialized behind a lock), each call here opens its own HTTP request and
holds no adapter-side lock. Concurrent callers therefore reach the runtime
concurrently -- ``ThreadPoolExecutor`` workers overlap in the runtime
itself, not just in Python (verified directly: see
``tests/test_http_adapter.py``). Whether that concurrency actually turns
into wall-clock speedup from there is the *runtime's* concurrency model,
not this adapter -- measured Ollama CPU-only serving requests one at a
time regardless of ``OLLAMA_NUM_PARALLEL``; llama-server's explicit
``--parallel`` slots are the alternative this adapter also speaks.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Literal

from .contracts import InferenceResponse

Backend = Literal["ollama", "llama_server"]


@dataclass(frozen=True, slots=True)
class HttpAdapterConfig:
    url: str
    model: str
    name: str = "http-runtime"
    timeout_s: float = 60.0
    backend: Backend = "ollama"
    num_thread: int | None = None
    """CPU threads Ollama uses per request (Ollama backend only -- llama-server
    fixes its thread count at server startup via its own -t flag, not per
    request). Left unset, Ollama defaults to ~all available cores *per
    request*: fine for one request at a time, but concurrent callers then
    oversubscribe the same cores against each other instead of getting real
    parallelism."""

    def __post_init__(self) -> None:
        if not self.url:
            raise ValueError("url must not be empty")
        if not self.model:
            raise ValueError("model must not be empty")
        if self.timeout_s <= 0:
            raise ValueError("timeout_s must be positive")
        if self.backend not in ("ollama", "llama_server"):
            raise ValueError(f"unsupported backend: {self.backend}")
        if self.num_thread is not None and self.num_thread < 1:
            raise ValueError("num_thread must be positive")


class HttpAdapter:
    """Talk to an Ollama or llama-server HTTP endpoint."""

    def __init__(self, config: HttpAdapterConfig) -> None:
        self.name = config.name
        self._backend = config.backend
        self._base_url = config.url.rstrip("/")
        self._model = config.model
        self._timeout_s = config.timeout_s
        self._num_thread = config.num_thread

    def _build_request(self, prompt: str, max_tokens: int) -> urllib.request.Request:
        if self._backend == "ollama":
            options: dict[str, int] = {"num_predict": max_tokens}
            if self._num_thread is not None:
                options["num_thread"] = self._num_thread
            body = {"model": self._model, "prompt": prompt, "stream": False, "options": options}
            endpoint = self._base_url + "/api/generate"
        else:
            body = {"prompt": prompt, "n_predict": max_tokens, "stream": False}
            endpoint = self._base_url + "/completion"
        payload = json.dumps(body).encode("utf-8")
        return urllib.request.Request(
            endpoint, data=payload, headers={"Content-Type": "application/json"}, method="POST",
        )

    def _parse_response(self, raw: bytes) -> InferenceResponse:
        try:
            value = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"http runtime returned non-JSON body: {raw[:200]!r}") from exc

        if self._backend == "ollama":
            if "response" not in value:
                raise RuntimeError(f"http runtime returned an unexpected payload: {raw[:200]!r}")
            return InferenceResponse(
                text=str(value.get("response", "")),
                input_tokens=int(value.get("prompt_eval_count", 0)),
                output_tokens=int(value.get("eval_count", 0)),
            )

        if "content" not in value:
            raise RuntimeError(f"http runtime returned an unexpected payload: {raw[:200]!r}")
        return InferenceResponse(
            text=str(value.get("content", "")),
            input_tokens=int(value.get("tokens_evaluated", 0)),
            output_tokens=int(value.get("tokens_predicted", 0)),
        )

    def infer(self, prompt: str, *, max_tokens: int) -> InferenceResponse:
        request = self._build_request(prompt, max_tokens)
        try:
            with urllib.request.urlopen(request, timeout=self._timeout_s) as response:
                raw = response.read()
        except urllib.error.URLError as exc:
            raise RuntimeError(f"http runtime request to {request.full_url} failed: {exc}") from exc
        return self._parse_response(raw)
