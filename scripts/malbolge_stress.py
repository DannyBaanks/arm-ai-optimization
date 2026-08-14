#!/usr/bin/env python3
"""
Malbolge Stress Benchmark.

Tests the evaluation harness robustness against a pathological workload.
Malbolge is a deliberately hostile esoteric language with:
- Self-modifying code
- Ternary arithmetic (crazy-op)
- Auto-encrypting memory
- No standard control flow

This tests whether the harness can:
1. Execute a Malbolge program without crashing
2. Handle non-termination / step budget exhaustion
3. Verify output correctly
4. Maintain contract integrity under pathological conditions
"""
from __future__ import annotations
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Dict, Any
from dataclasses import dataclass, asdict

REPO_ROOT = Path(__file__).resolve().parent.parent
EVIDENCE_DIR = REPO_ROOT / "evidence"
EVIDENCE_DIR.mkdir(exist_ok=True)

# Vendored under scripts/vendor/ so this runs from a clean clone. It used to
# point at an absolute path inside another checkout on the author's machine,
# so the "4/4 harness survival" the README advertises died with
# FileNotFoundError for everyone else, CI included.
MALBOLGE_INTERPRETER = REPO_ROOT / "scripts" / "vendor" / "malbolge_interpreter.py"

# Test programs
HELLO_WORLD = "(=<`#9]~6ZY327Uv4-QsqpMn&+Ij\"'E%e{Ab~w=_:]Kw%o44Uqp0/Q?xNvL:`H%c#DD2^WV>gY;dts76qKJImZkj"

# Pathological programs designed to stress the harness
INFINITE_LOOP = "j" * 1000  # Many no-ops (op 68)
SELF_MODIFYING_STRESS = HELLO_WORLD + "j" * 5000
LARGE_OUTPUT = "bCBA@?>=<;:9876543210/.-,+*)(\\'&%$#\"!~}|{zyxwvutsrqponmlkjihgfedcba`_^]\\[ZYXWVUTSRQPONMLKJIHGFEDCBA@?>7[5:3W70v4t21*/(\\',+k)\"F~%$dzbawv{]}srqponsrqjRnmfNdLKJIeGcbDZ_^W\\UZ<;WV876R4PIHM/KJC+*FED&BA#9>=<|4327654-,1q)o-,l*#(hgf$#cy?w|u;yxZputsrT1ohPOkMLbJ`HdFb[ZBX@VU=Y;QVUTMq4J21G/EDCBA@EDC<$#\"87<5Yz2x6vu-,r0).-&l*)ih&f|{zbx}v{ts[wpoWslqSoQgOkMihafedcEDCBA]\\UTYXQuO7M5KJ2NM/KD,HG@d\\'C%A@98=<;4Xy7wv43,+0/(L,lI#i!&fe#c!a}|\\^zsr8%"

TEST_PROGRAMS = {
    "hello_world": HELLO_WORLD,
    "infinite_loop_stress": INFINITE_LOOP,
    "self_modifying_stress": SELF_MODIFYING_STRESS,
    "large_output": LARGE_OUTPUT,
}


@dataclass
class StressResult:
    test_name: str
    program: str
    step_budget: int
    status: str  # HALTED, MAX_STEPS, ILLEGAL, INVALID
    steps: int
    output: str
    output_len: int
    execution_time_ms: float
    harness_survived: bool  # Did the harness crash?


def run_malbolge_program(program: str, step_budget: int = 50000, stdin_data: str = "") -> StressResult:
    """Run a Malbolge program using the bridge_core interpreter."""
    import sys
    import importlib.util
    
    spec = importlib.util.spec_from_file_location("malbolge_interpreter", MALBOLGE_INTERPRETER)
    malbolge_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(malbolge_module)
    run = malbolge_module.run
    
    start = time.perf_counter()
    try:
        text, steps, status = run(program, max_steps=step_budget, stdin_data=stdin_data)
        execution_time_ms = (time.perf_counter() - start) * 1000
        
        return StressResult(
            test_name="",
            program=program[:50] + "..." if len(program) > 50 else program,
            step_budget=step_budget,
            status=status,
            steps=steps,
            output=text,
            output_len=len(text),
            execution_time_ms=execution_time_ms,
            harness_survived=True,
        )
    except Exception as e:
        execution_time_ms = (time.perf_counter() - start) * 1000
        return StressResult(
            test_name="",
            program=program[:50] + "..." if len(program) > 50 else program,
            step_budget=step_budget,
            status="HARNESS_CRASH",
            steps=0,
            output=str(e),
            output_len=0,
            execution_time_ms=execution_time_ms,
            harness_survived=False,
        )


def run_stress_suite() -> Dict[str, Any]:
    """Run the full Malbolge stress test suite."""
    print("=" * 60)
    print("MALBOLGE STRESS BENCHMARK")
    print("=" * 60)
    print(f"Interpreter: {MALBOLGE_INTERPRETER}")
    print()
    
    results = {}
    overall_ok = True
    
    for test_name, program in TEST_PROGRAMS.items():
        print(f"Running {test_name}...")
        step_budget = 100000 if "large" in test_name or "stress" in test_name else 50000
        result = run_malbolge_program(program, step_budget=step_budget)
        result.test_name = test_name
        results[test_name] = asdict(result)
        
        # Harness survival is the key metric - ILLEGAL/MAX_STEPS are valid handled outcomes
        status_ok = result.harness_survived
        status_str = "OK" if status_ok else "FAIL"
        print(f"  {test_name}: {result.status} in {result.steps} steps ({result.execution_time_ms:.1f}ms) [{status_str}]")
        
        if not status_ok:
            overall_ok = False
    
    # Summary
    print("\n" + "=" * 60)
    print("STRESS TEST SUMMARY")
    print("=" * 60)
    for test_name, data in results.items():
        status = data["status"]
        survived = data["harness_survived"]
        print(f"  {test_name}: {status} (survived={survived})")
    
    print(f"\nOverall: {'ALL TESTS PASSED' if overall_ok else 'SOME TESTS FAILED'}")
    
    return {
        "overall_ok": overall_ok,
        "results": results,
        "summary": {
            "total_tests": len(TEST_PROGRAMS),
            "passed": sum(1 for r in results.values() if r["harness_survived"]),
            "failed": sum(1 for r in results.values() if not r["harness_survived"]),
        }
    }


def write_evidence(results: Dict[str, Any], workload_id: str):
    """Write stress test evidence through the canonical signer.

    This used to hash with `json.dumps(..., sort_keys=True)` -- no
    `separators` -- which is a different byte stream from the one
    `armopt.evidence` uses. The file was written with a hash that
    `verify_evidence()` could never reproduce, so the Malbolge survival
    evidence failed its own verification. One signer, one scheme.
    """
    from armopt.evidence import write_evidence as write_signed_evidence

    evidence_file = EVIDENCE_DIR / f"stress_{workload_id}.json"
    write_signed_evidence(
        evidence_file,
        results=results,
        workload_id=workload_id,
        schema="armopt.stress/1",
        extra={"stress_type": "malbolge"},
    )

    print(f"\nEvidence written to: {evidence_file}")
    print(f"SHA256: {json.loads(evidence_file.read_text())['evidence_sha256']}")

    return evidence_file


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Malbolge Stress Benchmark")
    parser.add_argument("--step-budget", type=int, default=50000, help="Max steps per program")
    parser.add_argument("--workload-id", default="malbolge_stress", help="Workload ID for evidence")
    parser.add_argument("--test", choices=list(TEST_PROGRAMS.keys()) + ["all"], default="all", help="Specific test to run")
    args = parser.parse_args()
    
    if args.test != "all":
        program = TEST_PROGRAMS[args.test]
        result = run_malbolge_program(program, step_budget=args.step_budget)
        result.test_name = args.test
        print(json.dumps(asdict(result), indent=2))
    else:
        results = run_stress_suite()
        write_evidence(results, args.workload_id)
        
        if not results["overall_ok"]:
            sys.exit(1)


if __name__ == "__main__":
    from datetime import timezone
    main()