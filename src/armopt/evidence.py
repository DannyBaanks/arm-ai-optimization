"""Stable evidence serialization for benchmark submissions."""
from __future__ import annotations

import hashlib
import json
import platform
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def canonical_hash(payload: dict[str, Any]) -> str:
    """The one and only definition of how evidence is hashed.

    Every producer of evidence must go through here. Two independent
    re-implementations of this rule had already drifted from it -- one omitted
    ``separators``, the other hashed the payload with an empty
    ``evidence_sha256`` placeholder still inside -- and both produced files
    that ``verify_evidence`` rejected. A signing scheme with three copies has
    three schemes.

    Any ``evidence_sha256`` already present is stripped before hashing, so a
    caller that pre-seeds the field cannot poison its own signature.
    """
    unsigned = {key: value for key, value in payload.items() if key != "evidence_sha256"}
    canonical = json.dumps(unsigned, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def write_evidence(path: Path, *, results: dict[str, Any], workload_id: str,
                   adapter: str | None = None, platform_name: str | None = None,
                   schema: str = "armopt.evidence/1",
                   extra: dict[str, Any] | None = None) -> None:
    """Write benchmark facts plus environment metadata atomically.

    ``schema`` and ``extra`` exist so that non-benchmark producers (stress
    suites, batch engines) can emit their own document shape without
    reimplementing the hashing rule -- see :func:`canonical_hash`.
    """
    payload: dict[str, Any] = {
        "schema": schema,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "workload_id": workload_id,
        "platform": platform_name or platform.platform(),
        "python": sys.version.split()[0],
        "results": results,
    }
    if adapter is not None:
        payload["adapter"] = adapter
    if extra:
        payload.update(extra)
    payload["evidence_sha256"] = canonical_hash(payload)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def verify_evidence(path: Path) -> tuple[bool, str]:
    """Recompute an evidence file's content hash and compare it to the
    ``evidence_sha256`` field written alongside it.

    "Signed evidence" means nothing without something that checks the
    signature -- this is that check. Returns ``(ok, message)``; ``ok`` is
    ``False`` for a missing/malformed signature or any content that has
    been edited since it was written, not just I/O errors.
    """
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return False, f"could not read {path} as evidence JSON: {exc}"

    if not isinstance(payload, dict) or "evidence_sha256" not in payload:
        return False, f"{path} has no evidence_sha256 field -- not a signed evidence file"

    recorded = payload["evidence_sha256"]
    recomputed = canonical_hash(payload)

    if recomputed == recorded:
        return True, f"evidence_sha256 matches recomputed hash ({recomputed[:12]}...)"
    return False, (
        f"HASH MISMATCH: recorded {recorded[:12]}... != recomputed {recomputed[:12]}... "
        "(file edited after signing, or corrupted)"
    )
