"""Portable workload loading from caller-provided files."""
from __future__ import annotations

import json
from pathlib import Path

from .contracts import Workload


def load_workload(path: Path, *, max_tokens: int = 64) -> Workload:
    """Load prompts from JSON array or JSONL objects without fixed paths."""
    if not path.is_file():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8")
    try:
        value = json.loads(text)
        if isinstance(value, list):
            prompts = [str(item) if not isinstance(item, dict) else str(item["prompt"])
                       for item in value]
        elif isinstance(value, dict):
            prompts = [str(value["prompt"])]
        else:
            raise ValueError("JSON workload must be an array or object")
    except json.JSONDecodeError:
        prompts = []
        for line in text.splitlines():
            if line.strip():
                item = json.loads(line)
                prompts.append(str(item["prompt"]) if isinstance(item, dict) else str(item))
    return Workload(prompts, max_tokens=max_tokens)
