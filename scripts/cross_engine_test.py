#!/usr/bin/env python3
"""
Cross-engine conformance test.

Runs the same workload through multiple engines (Python, Rust, etc.)
and verifies they all produce valid evidence with the same contract.
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any, List, Optional
from dataclasses import dataclass

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "evidence"
EVIDENCE_DIR.mkdir(exist_ok=True)


@dataclass
class EngineResult:
    engine: str
    success: bool
    evidence: Dict[str, Any] = None
    error: str = None
    metrics: Dict[str, Any] = None


def run_python_engine(requests: int, workers: int, repeats: int, workload_id: str) -> EngineResult:
    """Run Python reference engine."""
    evidence_file = EVIDENCE_DIR / f"cross_python_{workload_id}.json"
    cmd = [
        sys.executable, "-m", "armopt.cli",
        "--demo",
        "--requests", str(requests),
        "--workers", str(workers),
        "--mode", "both",
        "--repeats", str(repeats),
        "--evidence", str(evidence_file),
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120)
        if result.returncode != 0:
            return EngineResult(engine="python", success=False, error=result.stderr)
        
        with open(evidence_file) as f:
            evidence = json.load(f)
        
        return EngineResult(
            engine="python",
            success=True,
            evidence=evidence,
            metrics=extract_metrics(evidence)
        )
    except Exception as e:
        return EngineResult(engine="python", success=False, error=str(e))


def run_rust_engine(requests: int, workers: int, repeats: int, workload_id: str) -> EngineResult:
    """Run Rust native engine."""
    rust_bin = REPO_ROOT / "rust" / "armopt-native" / "target" / "release" / "armopt-native.exe"
    
    if not rust_bin.exists():
        return EngineResult(engine="rust", success=False, error=f"Rust binary not found: {rust_bin}")
    
    cmd = [
        str(rust_bin),
        "pipeline",
        "--requests", str(requests),
        "--workers", str(workers),
        "--repeats", str(repeats),
        "--workload-id", workload_id,
    ]
    
    try:
        # Run from the rust binary directory where evidence/ folder exists
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(rust_bin.parent), timeout=120)
        if result.returncode != 0:
            return EngineResult(engine="rust", success=False, error=result.stderr)
        
        # Pipeline writes to evidence/{workload_id}_pipeline.json
        evidence_path = rust_bin.parent / "evidence" / f"{workload_id}_pipeline.json"
        if evidence_path.exists():
            with open(evidence_path) as f:
                evidence = json.load(f)
        else:
            return EngineResult(engine="rust", success=False, error=f"Evidence file not generated at {evidence_path}")
        
        return EngineResult(
            engine="rust",
            success=True,
            evidence=evidence,
            metrics=extract_metrics(evidence)
        )
    except Exception as e:
        return EngineResult(engine="rust", success=False, error=str(e))


def run_cobol_engine(requests: int, workers: int, repeats: int, workload_id: str) -> EngineResult:
    """Run COBOL batch engine (Python reference implementation)."""
    adapter_path = REPO_ROOT / "rust" / "cobol-adapter" / "cobol_adapter.py"
    evidence_file = EVIDENCE_DIR / f"cross_cobol_{workload_id}.json"
    
    if not adapter_path.exists():
        return EngineResult(engine="cobol", success=False, error=f"COBOL adapter not found: {adapter_path}")
    
    # Use the E22 data directory
    data_dir = Path(r"C:\Development\ISyCo\E22_cobol_heavyweight\workload\data_p1k")
    out_dir = Path(r"C:\Development\ISyCo Git\Arm AI Optimization\rust\cobol-adapter\out_cross_test")
    
    cmd = [
        sys.executable, str(adapter_path),
        "--data-dir", str(data_dir),
        "--out-dir", str(out_dir),
        "--workload-id", workload_id,
        "--evidence", str(evidence_file),
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(REPO_ROOT), timeout=120)
        if result.returncode != 0:
            return EngineResult(engine="cobol", success=False, error=result.stderr)
        
        with open(evidence_file) as f:
            evidence = json.load(f)
        
        # COBOL engine doesn't have baseline/dataflow, adapt metrics
        metrics = {
            "baseline": {
                "wall_ms": evidence.get("results", {}).get("wall_ms", 0),
                "tokens_per_second": 0,
                "output_tokens": evidence.get("results", {}).get("n_in", 0),
            },
            "dataflow": {
                "wall_ms": evidence.get("results", {}).get("wall_ms", 0),
                "tokens_per_second": 0,
                "output_tokens": evidence.get("results", {}).get("n_in", 0),
            },
            "speedup_wall": 1.0,
        }
        
        return EngineResult(
            engine="cobol",
            success=True,
            evidence=evidence,
            metrics=metrics
        )
    except Exception as e:
        return EngineResult(engine="cobol", success=False, error=str(e))


def extract_metrics(evidence: Dict[str, Any]) -> Dict[str, Any]:
    """Extract comparable metrics from evidence."""
    results = evidence.get("results", {})
    baseline = results.get("baseline", {})
    dataflow = results.get("dataflow", {})
    speedup = results.get("speedup_wall")
    
    return {
        "baseline": {
            "wall_ms": baseline.get("wall_ms"),
            "mean_latency_ms": baseline.get("mean_latency_ms"),
            "p95_latency_ms": baseline.get("p95_latency_ms"),
            "tokens_per_second": baseline.get("tokens_per_second"),
            "output_tokens": baseline.get("output_tokens"),
            "repeats": results.get("repeats"),
        },
        "dataflow": {
            "wall_ms": dataflow.get("wall_ms"),
            "mean_latency_ms": dataflow.get("mean_latency_ms"),
            "p95_latency_ms": dataflow.get("p95_latency_ms"),
            "tokens_per_second": dataflow.get("tokens_per_second"),
            "output_tokens": dataflow.get("output_tokens"),
            "repeats": results.get("repeats"),
        },
        "speedup_wall": speedup,
    }


def validate_contract(evidence: Dict[str, Any], engine: str) -> List[str]:
    """Validate evidence has required contract fields."""
    errors = []
    
    required_top = ["schema", "created_at", "workload_id", "adapter", "platform", "results", "evidence_sha256"]
    for field in required_top:
        if field not in evidence:
            errors.append(f"Missing top-level field: {field}")
    
    if "results" not in evidence:
        errors.append("Missing results object")
        return errors
    
    results = evidence["results"]
    
    # COBOL has a different contract structure (batch processing)
    if engine == "cobol":
        required_cobol = ["n_in", "accept", "adjust", "reject", "delta", "check1", "check2", "wall_ms", "engine"]
        for field in required_cobol:
            if field not in results:
                errors.append(f"Missing COBOL field: {field}")
        return errors
    
    # Inference engines (Python, Rust) have baseline/dataflow structure
    if "baseline" not in results or "dataflow" not in results:
        errors.append("Missing baseline or dataflow in results")
    else:
        if "repeats" not in results:
            errors.append("Missing results.repeats")
        
        for mode in ["baseline", "dataflow"]:
            mode_data = results.get(mode, {})
            required_mode = ["adapter", "mode", "requests", "workers", "wall_ms", "mean_latency_ms", "p95_latency_ms", "output_tokens", "tokens_per_second"]
            for field in required_mode:
                if field not in mode_data:
                    errors.append(f"Missing {mode}.{field}")
    
    return errors


def compare_contracts(evidence1: Dict, evidence2: Dict) -> List[str]:
    """Compare contract compliance between engines."""
    issues = []
    
    # Both should have same top-level structure
    results1 = evidence1.get("results", {})
    results2 = evidence2.get("results", {})
    
    for mode in ["baseline", "dataflow"]:
        mode1 = results1.get(mode, {})
        mode2 = results2.get(mode, {})
        
        # Check both have same mode field
        if mode1.get("mode") != mode2.get("mode"):
            issues.append(f"Mode mismatch in {mode}: engine1={mode1.get('mode')} engine2={mode2.get('mode')}")
        
        # Check requests match
        if mode1.get("requests") != mode2.get("requests"):
            issues.append(f"Requests mismatch in {mode}: engine1={mode1.get('requests')} engine2={mode2.get('requests')}")
        
        # Check workers match (baseline should be 1, dataflow should be workers)
        if mode1.get("workers") != mode2.get("workers"):
            issues.append(f"Workers mismatch in {mode}: engine1={mode1.get('workers')} engine2={mode2.get('workers')}")
        
        # Check output_tokens match (should be identical)
        if mode1.get("output_tokens") != mode2.get("output_tokens"):
            issues.append(f"Output tokens mismatch in {mode}: engine1={mode1.get('output_tokens')} engine2={mode2.get('output_tokens')}")
    
    return issues


def get_engine_type(engine: str) -> str:
    """Return the contract type for an engine."""
    batch_engines = {"cobol"}
    if engine in batch_engines:
        return "batch"
    return "inference"


def main():
    print("=" * 60)
    print("CROSS-ENGINE CONFORMANCE TEST")
    print("=" * 60)
    
    requests = 100
    workers = 4
    repeats = 3
    workload_id = "cross_engine_test"
    
    engines = [
        ("python", lambda: run_python_engine(requests, workers, repeats, workload_id)),
        ("rust", lambda: run_rust_engine(requests, workers, repeats, workload_id)),
        ("cobol", lambda: run_cobol_engine(requests, workers, repeats, workload_id)),
    ]
    
    results = {}
    for name, runner in engines:
        print(f"\nRunning {name} engine...")
        result = runner()
        results[name] = result
        
        if result.success:
            print(f"  {name}: OK")
            print(f"    baseline: {result.metrics['baseline']['wall_ms']:.0f}ms, {result.metrics['baseline']['tokens_per_second']:.0f} tok/s")
            print(f"    dataflow: {result.metrics['dataflow']['wall_ms']:.0f}ms, {result.metrics['dataflow']['tokens_per_second']:.0f} tok/s")
            print(f"    speedup: {result.metrics['speedup_wall']:.2f}x")
        else:
            print(f"  {name}: FAILED - {result.error}")
    
    print("\n" + "=" * 60)
    print("CONTRACT VALIDATION")
    print("=" * 60)
    
    all_ok = True
    for name, result in results.items():
        if result.success:
            errors = validate_contract(result.evidence, name)
            if errors:
                print(f"\n{name} CONTRACT ERRORS:")
                for e in errors:
                    print(f"  - {e}")
                all_ok = False
            else:
                print(f"{name} contract: OK")
        else:
            print(f"\n{name}: SKIPPED (engine failed)")
            all_ok = False
    
    if all_ok:
        print("\n" + "=" * 60)
        print("CROSS-ENGINE CONTRACT COMPARISON")
        print("=" * 60)
        
        # Compare all successful engines
        successful_engines = {name: result for name, result in results.items() if result.success}
        
        if len(successful_engines) >= 2:
            engine_names = list(successful_engines.keys())
            for i in range(len(engine_names)):
                for j in range(i + 1, len(engine_names)):
                    name1, name2 = engine_names[i], engine_names[j]
                    
                    # Only compare engines with same contract type
                    batch_engines = {"cobol"}
                    type1 = "batch" if name1 in {"cobol"} else "inference"
                    type2 = "batch" if name2 in {"cobol"} else "inference"
                    
                    if type1 != type2:
                        print(f"\n{name1} vs {name2}: Different contract types (skipping comparison)")
                        continue
                    
                    ev1 = successful_engines[name1].evidence
                    ev2 = successful_engines[name2].evidence
                    issues = compare_contracts(ev1, ev2)
                    if issues:
                        print(f"\n{name1} vs {name2} CONTRACT MISMATCHES:")
                        for issue in issues:
                            print(f"  - {issue}")
                        all_ok = False
                    else:
                        print(f"\n{name1} vs {name2}: Contract fields match OK")
        else:
            print("Need at least 2 successful engines for comparison")
    
    print("\n" + "=" * 60)
    if all_ok:
        print("RESULT: ALL TESTS PASSED")
        return 0
    else:
        print("RESULT: SOME TESTS FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())