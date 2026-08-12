"""Persistent JSONL subprocess adapter for interchangeable runtimes."""
from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .contracts import InferenceResponse


@dataclass(frozen=True, slots=True)
class JsonlAdapterConfig:
    command: Sequence[str]
    name: str = "jsonl-runtime"
    cwd: Path | None = None

    def __post_init__(self) -> None:
        if not self.command:
            raise ValueError("command must not be empty")


class JsonlAdapter:
    """Keep one runtime alive and exchange one JSON object per line.

    Request: ``{"prompt": ..., "max_tokens": ...}``
    Response: ``{"text": ..., "input_tokens": ..., "output_tokens": ...}``
    """

    def __init__(self, config: JsonlAdapterConfig) -> None:
        self.name = config.name
        self._process = subprocess.Popen(
            list(config.command),
            cwd=str(config.cwd) if config.cwd else None,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        self._lock = threading.Lock()

    def infer(self, prompt: str, *, max_tokens: int) -> InferenceResponse:
        if self._process.poll() is not None:
            raise RuntimeError(f"runtime exited with code {self._process.returncode}")
        request = json.dumps({"prompt": prompt, "max_tokens": max_tokens})
        with self._lock:
            assert self._process.stdin is not None
            assert self._process.stdout is not None
            self._process.stdin.write(request + "\n")
            self._process.stdin.flush()
            line = self._process.stdout.readline()
        if not line:
            raise RuntimeError("runtime closed stdout without a response")
        value = json.loads(line)
        return InferenceResponse(
            text=str(value.get("text", "")),
            input_tokens=int(value.get("input_tokens", 0)),
            output_tokens=int(value.get("output_tokens", 0)),
        )

    def close(self) -> None:
        if self._process.poll() is None:
            self._process.terminate()
            self._process.wait(timeout=5)
        for stream in (self._process.stdin, self._process.stdout, self._process.stderr):
            if stream is not None:
                stream.close()

    def __enter__(self) -> "JsonlAdapter":
        return self

    def __exit__(self, exc_type, exc_value, traceback) -> None:
        self.close()
