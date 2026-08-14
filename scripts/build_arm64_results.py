#!/usr/bin/env python3
"""Build results/arm64/ from evidence measured on a real aarch64 host.

This script does not run benchmarks. It reads the signed evidence produced by
the ``arm64-benchmark.yml`` workflow on a GitHub-hosted ``ubuntu-24.04-arm``
runner, verifies every signature, and renders the comparison + human summary
from those files alone.

The separation is deliberate. ``generate_comparison.py`` runs the in-memory
demo adapter and therefore describes whatever machine it ran on -- which is
usually a developer laptop. Pointing it at ``results/arm64/`` is how this repo
ended up with files named ``arm64_*`` whose contents read ``"architecture":
"AMD64"``. Arm64 results now come only from Arm64 evidence, and this script
refuses to write anything if the evidence says otherwise.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from armopt.evidence import verify_evidence  # noqa: E402

CI_EVIDENCE_DIR = REPO_ROOT / "evidence" / "arm64_ci"
RESULTS_DIR = REPO_ROOT / "results" / "arm64"

# Ordered: each entry is one measured configuration. The label is what the
# README shows; the file is what it is derived from.
CONFIGURATIONS = [
    ("arm64_naive.json", "Ollama, default per-request threading (OLLAMA_NUM_PARALLEL=4)"),
    ("arm64_capped.json", "Ollama, capped per-request threading (num_thread=1)"),
    ("arm64_llama_server.json", "llama-server, --parallel 4 -t 1"),
]
SELECTION_FILE = "selection.json"
HOST_FILE = "host.json"


def load_verified(path: Path) -> dict[str, Any]:
    """Load an evidence file, refusing anything whose signature does not check."""
    ok, message = verify_evidence(path)
    if not ok:
        raise SystemExit(f"refusing to build results from unverified evidence: {path.name}: {message}")
    return json.loads(path.read_text(encoding="utf-8"))


def require_aarch64(payload: dict[str, Any], name: str) -> None:
    """Guard the mislabeling bug this script exists to prevent."""
    platform_string = payload.get("platform", "")
    if "aarch64" not in platform_string:
        raise SystemExit(
            f"refusing to write Arm64 results: {name} was measured on "
            f"{platform_string!r}, which is not aarch64"
        )


def summarize(mode_block: dict[str, Any]) -> dict[str, Any]:
    return {
        "requests": mode_block["requests"],
        "workers": mode_block["workers"],
        "wall_ms": mode_block["wall_ms"],
        "mean_latency_ms": mode_block["mean_latency_ms"],
        "p95_latency_ms": mode_block["p95_latency_ms"],
        "output_tokens": mode_block["output_tokens"],
        "tokens_per_second": mode_block["tokens_per_second"],
    }


def replace_block(text: str, marker: str, body: str) -> str:
    """Swap the contents between <!-- marker:START --> and <!-- marker:END -->."""
    start, end = f"<!-- {marker}:START -->", f"<!-- {marker}:END -->"
    head, _, rest = text.partition(start)
    _, _, tail = rest.partition(end)
    if not rest or not tail:
        raise SystemExit(f"README.md is missing the {marker} markers")
    return f"{head}{start}\n{body}\n{end}{tail}"


def render_repo_readme(configurations, scheduler_decision, host) -> None:
    """Regenerate the measured-numbers blocks of the top-level README.

    The README is the document a judge actually reads, and re-measurement moves
    every decimal in it. Hand-maintaining those tables is how a repo ends up
    quoting four mutually contradictory speedups. So the prose is written to
    survive re-measurement and the numbers are generated from the same evidence
    that produced results/arm64/ -- narrative derived from evidence, which is
    the claim this project makes about itself.
    """
    best = max(configurations, key=lambda c: c["speedup"]["wall_time"])
    rows = "\n".join(
        f"| {'**' + c['label'] + '**' if c is best else c['label']} | "
        f"{c['baseline']['wall_ms'] / 1000:.2f}s | {c['dataflow']['wall_ms'] / 1000:.2f}s | "
        f"**{c['speedup']['wall_time']}x** | "
        f"{c['baseline']['tokens_per_second']:.1f} -> {c['dataflow']['tokens_per_second']:.1f} |"
        for c in configurations
    )
    blocks = {"ARM64_TABLE": (
        "| Runtime configuration | Sequential | Dataflow | Wall-time | tokens/s |\n"
        "|---|---|---|---|---|\n" + rows
    )}

    if scheduler_decision:
        by_adapter = {c["adapter"]: c for c in scheduler_decision["candidates"]}
        # First match wins: two Ollama configurations share one adapter string,
        # and the scheduler was handed the first (naive) one, not the capped
        # variant. Overwriting here would credit Ollama with a speedup the
        # scheduler never saw.
        speedup_by_adapter: dict[str, float] = {}
        for c in configurations:
            speedup_by_adapter.setdefault(c["adapter"], c["speedup"]["wall_time"])
        selected = scheduler_decision["selected"]
        lines = []
        for adapter, cand in by_adapter.items():
            name = "Ollama" if ":ollama:" in adapter else "llama-server"
            chosen = adapter == selected
            speedup = speedup_by_adapter.get(adapter)
            lines.append(
                f"| {'**' + name + '** (deployed)' if chosen else name} | "
                f"{'**' if chosen else ''}{cand['mean_latency_ms']:,.0f} ms{'**' if chosen else ''} | "
                f"{'**' if chosen else ''}{cand['output_tokens_per_second']:.1f}{'**' if chosen else ''} | "
                f"{speedup if speedup is not None else 'n/a'}x |"
            )
        blocks["SCHEDULER_TABLE"] = (
            "| | mean latency | tokens/s | wall-time speedup |\n"
            "|---|---|---|---|\n" + "\n".join(lines)
        )

    if host:
        lscpu = host.get("lscpu", "")
        model = next(
            (l.split(":", 1)[1].strip() for l in lscpu.splitlines()
             if l.startswith("Model name:")),
            "unknown",
        )
        blocks["ARM64_HOST"] = (
            f"GitHub-hosted `ubuntu-24.04-arm` runner: **{model}**, "
            f"{host.get('nproc', '?')} cores, `{host.get('platform', '')}`. "
            f"Recorded by the runner itself in "
            f"[`evidence/arm64_ci/host.json`](evidence/arm64_ci/host.json)."
        )

    # The Devpost copy carries the same tables; a submission quoting different
    # numbers than the repo it links to is the same failure in a worse place.
    for path in (REPO_ROOT / "README.md", REPO_ROOT / "docs" / "DEVPOST.md"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for marker, body in blocks.items():
            if f"<!-- {marker}:START -->" in text:
                text = replace_block(text, marker, body)
        path.write_text(text, encoding="utf-8")


def main() -> None:
    if not CI_EVIDENCE_DIR.is_dir():
        raise SystemExit(f"no Arm64 CI evidence at {CI_EVIDENCE_DIR}")

    configurations = []
    platform_string = None
    python_version = None

    for filename, label in CONFIGURATIONS:
        path = CI_EVIDENCE_DIR / filename
        if not path.is_file():
            raise SystemExit(f"missing expected Arm64 evidence file: {path}")

        payload = load_verified(path)
        require_aarch64(payload, filename)

        platform_string = platform_string or payload["platform"]
        python_version = python_version or payload["python"]

        results = payload["results"]
        baseline = results["baseline"]
        dataflow = results["dataflow"]

        configurations.append({
            "label": label,
            "workload_id": payload["workload_id"],
            "adapter": payload["adapter"],
            "measured_at": payload["created_at"],
            "repeats": results["repeats"],
            "baseline": summarize(baseline),
            "dataflow": summarize(dataflow),
            "speedup": {
                "wall_time": results["speedup_wall"],
                "tokens_per_second": round(
                    dataflow["tokens_per_second"] / baseline["tokens_per_second"], 3
                ),
                # Latency rises under dataflow because concurrent requests share
                # the same cores. Reported, not hidden.
                "mean_latency": round(
                    baseline["mean_latency_ms"] / dataflow["mean_latency_ms"], 3
                ),
            },
            "evidence_file": f"evidence/arm64_ci/{filename}",
            "evidence_sha256": payload["evidence_sha256"],
        })

    best = max(configurations, key=lambda c: c["speedup"]["wall_time"])

    selection_path = CI_EVIDENCE_DIR / SELECTION_FILE
    scheduler_decision = (
        json.loads(selection_path.read_text(encoding="utf-8"))
        if selection_path.is_file() else None
    )

    # Written by the workflow from /proc/cpuinfo and lscpu on the runner. Absent
    # for evidence captured before that step existed -- the rest still renders,
    # the host block just stays unclaimed rather than being guessed at.
    host_path = CI_EVIDENCE_DIR / HOST_FILE
    host = json.loads(host_path.read_text(encoding="utf-8")) if host_path.is_file() else None

    # Deliberately the timestamp of the last measurement, not of this render.
    # A document describing a benchmark should be dated by the benchmark. It
    # also makes this script's output a pure function of its input, so CI can
    # re-run it and assert the tree is unchanged -- see .github/workflows/ci.yml.
    measured_at = max(c["measured_at"] for c in configurations)

    comparison = {
        "schema": "armopt.comparison/2",
        "measured_at": measured_at,
        "provenance": {
            "source": "GitHub Actions workflow arm64-benchmark.yml",
            "runner": "ubuntu-24.04-arm (GitHub-hosted Arm64, Azure Cobalt)",
            "note": (
                "The workflow asserts uname -m == aarch64 and fails the job "
                "otherwise, so evidence cannot be produced off-target."
            ),
        },
        "platform": {
            "architecture": "aarch64",
            "platform_string": platform_string,
            "python": python_version,
            "host": host,
        },
        "model": {
            "name": "qwen2.5-0.5b-instruct",
            "formats": ["ollama q4", "GGUF q4_k_m"],
        },
        "configurations": configurations,
        "best_wall_time_speedup": {
            "label": best["label"],
            "value": best["speedup"]["wall_time"],
        },
        "scheduler_decision": scheduler_decision,
    }

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    (RESULTS_DIR / "comparison.json").write_text(
        json.dumps(comparison, indent=2) + "\n", encoding="utf-8"
    )

    rows = "\n".join(
        f"| {c['label']} | {c['baseline']['wall_ms'] / 1000:.2f}s | "
        f"{c['dataflow']['wall_ms'] / 1000:.2f}s | **{c['speedup']['wall_time']}x** | "
        f"{c['baseline']['tokens_per_second']:.1f} -> {c['dataflow']['tokens_per_second']:.1f} |"
        for c in configurations
    )
    hashes = "\n".join(
        f"| `{c['evidence_file']}` | `{c['evidence_sha256'][:16]}...` |"
        for c in configurations
    )

    selected = (
        scheduler_decision.get("selected", "n/a") if scheduler_decision else "n/a"
    )

    if host:
        host_line = (
            f"- **Host**: {host.get('nproc', '?')} vCPU"
            f"{', ' + host['cpu_model_line'] if host.get('cpu_model_line') else ''}"
            f" (recorded by the runner in `evidence/arm64_ci/host.json`)\n"
        )
    else:
        host_line = (
            "- **Host**: core count and silicon not yet captured; the next CI run "
            "records them to `evidence/arm64_ci/host.json`\n"
        )

    summary = f"""# Arm64 Benchmark Results

Measured on a GitHub-hosted `ubuntu-24.04-arm` runner. The workflow asserts
`uname -m == aarch64` before producing anything, so these numbers cannot come
from an x86 host.

- **Platform**: `{platform_string}`
{host_line}- **Python**: {python_version}
- **Model**: qwen2.5-0.5b-instruct
- **Workload**: 8 requests, 3 repeats, 4 workers in dataflow mode
- **Measured**: {measured_at}

## Measured configurations

| Configuration | Sequential | Dataflow | Wall-time speedup | tokens/s |
|---|---|---|---|---|
{rows}

**Best wall-time speedup**: {best['speedup']['wall_time']}x ({best['label']}).

## Scheduler decision

The scheduler selected: **`{selected}`**

It optimizes for mean latency and throughput, not wall-time speedup. The
configuration with the best wall-time speedup is not the one it deploys --
see the repository README for why that disagreement is the point.

## Evidence integrity

| File | evidence_sha256 |
|---|---|
{hashes}

Verify any of them:

```bash
python -c "from pathlib import Path; from armopt.evidence import verify_evidence; \\
print(verify_evidence(Path('evidence/arm64_ci/arm64_llama_server.json')))"
```

Regenerate this directory from the evidence:

```bash
python scripts/build_arm64_results.py
```
"""
    (RESULTS_DIR / "README.md").write_text(summary, encoding="utf-8")

    render_repo_readme(configurations, scheduler_decision, host)

    print(f"Wrote {RESULTS_DIR / 'comparison.json'}")
    print(f"Wrote {RESULTS_DIR / 'README.md'}")
    print(f"Configurations: {len(configurations)}, all verified aarch64")
    print(f"Best wall-time speedup: {best['speedup']['wall_time']}x -- {best['label']}")
    print(f"Scheduler selected: {selected}")


if __name__ == "__main__":
    main()
