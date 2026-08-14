#!/usr/bin/env python3
"""
Generate reproducible Arm64 comparison results.

Runs baseline (sequential) and optimized (dataflow) benchmarks,
produces signed evidence, and writes comparison.json with SHA256s.
"""
from __future__ import annotations
import json
import subprocess
import hashlib
import platform
import sys
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "evidence"
RESULTS_DIR = REPO_ROOT / "results" / "arm64"
WORKLOAD_FILE = REPO_ROOT / "workloads" / "demo.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_benchmark(mode: str, workers: int, evidence_name: str) -> Dict[str, Any]:
    """Run armopt.cli and return parsed JSON result."""
    evidence_path = EVIDENCE_DIR / evidence_name

    cmd = [
        sys.executable, "-m", "armopt.cli",
        "--demo",
        "--requests", "100",
        "--workers", str(workers),
        "--mode", mode,
        "--evidence", str(evidence_path),
        "--repeats", "3",
    ]

    print(f"Running {mode} (workers={workers})...")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT))

    if result.returncode != 0:
        print(f"STDERR: {result.stderr}")
        raise RuntimeError(f"Benchmark failed: {result.stderr}")

    # Parse the JSON output (first JSON object in stdout)
    stdout = result.stdout.strip()
    # Find the first complete JSON object
    brace_count = 0
    json_end = 0
    for i, ch in enumerate(stdout):
        if ch == '{':
            brace_count += 1
        elif ch == '}':
            brace_count -= 1
            if brace_count == 0:
                json_end = i + 1
                break
    data = json.loads(stdout[:json_end])

    return {
        "mode": mode,
        "workers": workers,
        "evidence_file": evidence_name,
        "evidence_sha256": sha256_file(evidence_path),
        "metrics": {
            "total_seconds": data.get("wall_ms", 0) / 1000.0,
            "p50_ms": data.get("mean_latency_ms", 0),
            "p95_ms": data.get("p95_latency_ms", 0),
            "throughput_rps": (100 / (data.get("wall_ms", 1) / 1000.0)) if data.get("wall_ms") else 0,
            "tokens_per_second": data.get("tokens_per_second", 0),
            "output_tokens": data.get("output_tokens", 0),
        }
    }


def get_platform_info() -> Dict[str, str]:
    return {
        "architecture": platform.machine(),
        "os": f"{platform.system()} {platform.release()}",
        "cpu": platform.processor() or "unknown",
        "python": platform.python_version(),
    }


def get_runtime_info() -> Dict[str, Any]:
    return {
        "name": "demo-adapter",
        "version": "0.1.0",
        "config": "in-memory demo (no external runtime)",
    }


def get_model_info() -> Dict[str, str]:
    return {
        "name": "demo-model",
        "format": "in-memory",
    }


def get_workload_info() -> Dict[str, Any]:
    return {
        "requests": 100,
        "workers": 4,
        "repeats": 3,
        "mode": "both",
    }


def main():
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    EVIDENCE_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 60)
    print("ARM AI OPTIMIZATION — Reproducible Comparison Generator")
    print("=" * 60)

    # Run baseline (sequential)
    baseline = run_benchmark("sequential", 1, "arm64_sequential.json")

    # Run optimized (dataflow)
    optimized = run_benchmark("dataflow", 4, "arm64_dataflow.json")

    # Compute speedups
    speedup = {
        "wall_time": round(baseline["metrics"]["total_seconds"] / optimized["metrics"]["total_seconds"], 3),
        "p50_latency": round(baseline["metrics"]["p50_ms"] / optimized["metrics"]["p50_ms"], 3),
        "p95_latency": round(baseline["metrics"]["p95_ms"] / optimized["metrics"]["p95_ms"], 3),
        "throughput": round(optimized["metrics"]["throughput_rps"] / baseline["metrics"]["throughput_rps"], 3),
        "tokens_per_second": round(optimized["metrics"]["tokens_per_second"] / baseline["metrics"]["tokens_per_second"], 3),
    }

    # Build comparison.json
    comparison = {
        "schema": "armopt.comparison/1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platform": get_platform_info(),
        "runtime": get_runtime_info(),
        "model": get_model_info(),
        "workload": get_workload_info(),
        "metrics": {
            "baseline": baseline["metrics"],
            "optimized": optimized["metrics"],
            "speedup": speedup,
        },
        "evidence": {
            "baseline_sha256": baseline["evidence_sha256"],
            "optimized_sha256": optimized["evidence_sha256"],
            "baseline_file": baseline["evidence_file"],
            "optimized_file": optimized["evidence_file"],
        },
    }

    # Write comparison.json
    comparison_path = RESULTS_DIR / "comparison.json"
    comparison_path.write_text(json.dumps(comparison, indent=2))

    # Write individual evidence copies to results/ for easy access
    for ev_name in [baseline["evidence_file"], optimized["evidence_file"]]:
        src = EVIDENCE_DIR / ev_name
        dst = RESULTS_DIR / ev_name
        dst.write_text(src.read_text())

    # Write environment.json
    env_info = {
        "platform": get_platform_info(),
        "runtime": get_runtime_info(),
        "model": get_model_info(),
        "workload": get_workload_info(),
        "generated_at": comparison["generated_at"],
    }
    (RESULTS_DIR / "environment.json").write_text(json.dumps(env_info, indent=2))

    # Write human-readable summary
    summary = f"""# Arm64 Benchmark Results

**Generated**: {comparison['generated_at']}

## Platform
- Architecture: {comparison['platform']['architecture']}
- OS: {comparison['platform']['os']}
- CPU: {comparison['platform']['cpu']}
- Python: {comparison['platform']['python']}

## Runtime
- Name: {comparison['runtime']['name']}
- Config: {comparison['runtime']['config']}

## Model
- Name: {comparison['model']['name']}

## Workload
- Requests: {comparison['workload']['requests']}
- Workers: {comparison['workload']['workers']}
- Repeats: {comparison['workload']['repeats']}

## Metrics

| Metric | Baseline (sequential) | Optimized (dataflow) | Speedup |
|--------|----------------------|---------------------|---------|
| Total Time | {comparison['metrics']['baseline']['total_seconds']:.2f}s | {comparison['metrics']['optimized']['total_seconds']:.2f}s | **{comparison['metrics']['speedup']['wall_time']}×** |
| p50 Latency | {comparison['metrics']['baseline']['p50_ms']:.1f}ms | {comparison['metrics']['optimized']['p50_ms']:.1f}ms | **{comparison['metrics']['speedup']['p50_latency']}×** |
| p95 Latency | {comparison['metrics']['baseline']['p95_ms']:.1f}ms | {comparison['metrics']['optimized']['p95_ms']:.1f}ms | **{comparison['metrics']['speedup']['p95_latency']}×** |
| Throughput | {comparison['metrics']['baseline']['throughput_rps']:.2f} req/s | {comparison['metrics']['optimized']['throughput_rps']:.2f} req/s | **{comparison['metrics']['speedup']['throughput']}×** |
| Tokens/sec | {comparison['metrics']['baseline']['tokens_per_second']:.0f} | {comparison['metrics']['optimized']['tokens_per_second']:.0f} | **{comparison['metrics']['speedup']['tokens_per_second']}×** |

## Evidence Integrity

| File | SHA256 |
|------|--------|
| {baseline['evidence_file']} | {baseline['evidence_sha256']} |
| {optimized['evidence_file']} | {optimized['evidence_sha256']} |

Verify with:
```bash
python -c "from pathlib import Path; from armopt.evidence import verify_evidence; print(verify_evidence(Path('results/arm64/{baseline['evidence_file']}')))"
```
"""
    (RESULTS_DIR / "README.md").write_text(summary)

    print()
    print("=" * 60)
    print("DONE")
    print("=" * 60)
    print(f"Results written to: {RESULTS_DIR}")
    print(f"  - comparison.json")
    print(f"  - environment.json")
    print(f"  - {baseline['evidence_file']}")
    print(f"  - {optimized['evidence_file']}")
    print(f"  - README.md")
    print()
    print("Speedup Summary:")
    for k, v in speedup.items():
        print(f"  {k}: {v}×")


if __name__ == "__main__":
    main()