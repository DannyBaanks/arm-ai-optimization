"""Stable evidence serialization for benchmark submissions."""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_evidence(path: Path, *, results: dict[str, Any], workload_id: str,
                   adapter: str, platform_name: str | None = None) -> None:
    """Write benchmark facts plus environment metadata atomically."""
    payload = {
        "schema": "armopt.evidence/1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "workload_id": workload_id,
        "adapter": adapter,
        "platform": platform_name or platform.platform(),
        "python": sys.version.split()[0],
        "results": results,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    payload["evidence_sha256"] = hashlib.sha256(canonical).hexdigest()
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)
