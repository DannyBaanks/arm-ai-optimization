#!/usr/bin/env python3
"""
COBOL Engine Adapter for Arm AI Optimization Harness.

This adapter runs the E22 COBOL batch processing workload through the
same contract as other engines (Python, Rust, WASM).

The native COBOL binary (nightly.exe) requires GnuCOBOL runtime.
This adapter uses the Python reference implementation as a fallback
which produces byte-identical output to the COBOL engine.
"""
from __future__ import annotations
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, Optional

# Add the E22 COBOL engine to path
E22_ROOT = Path(r"C:\Development\ISyCo\E22_cobol_heavyweight\workload")
sys.path.insert(0, str(E22_ROOT))

# Change to the workload directory to ensure imports work
original_cwd = Path.cwd()
os.chdir(E22_ROOT)

try:
    from engine import run_engine
finally:
    os.chdir(original_cwd)


class CobolAdapter:
    """COBOL engine adapter using Python reference implementation."""
    
    def __init__(self, use_native: bool = False):
        self.use_native = use_native
        self.native_binary = E22_ROOT / "nightly.exe"
        self.python_engine = E22_ROOT / "engine.py"
    
    def _run_native(self, data_dir: Path, out_dir: Path) -> Dict[str, Any]:
        """Run the native COBOL binary."""
        if not self.native_binary.exists():
            return {"error": f"Native binary not found: {self.native_binary}"}
        
        out_dir.mkdir(parents=True, exist_ok=True)
        
        try:
            start = time.perf_counter()
            result = subprocess.run(
                [str(self.native_binary), str(data_dir), str(out_dir)],
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(E22_ROOT)
            )
            wall_ms = int((time.perf_counter() - start) * 1000)
            
            if result.returncode != 0:
                return {"error": f"COBOL engine failed: {result.stderr}"}
            
            # Parse output files to get stats
            # The COBOL engine produces: outcomes.dat, balances.dat, accumulators.dat, report.txt, reconcile.txt
            # We'll read the reconcile.txt which has the summary
            reconcile_file = out_dir / "reconcile.txt"
            if reconcile_file.exists():
                content = reconcile_file.read_text().strip()
                # Format: E|TOTALS|...|check1|check2
                parts = content.split("|")
                if len(parts) >= 10:
                    return {
                        "n_in": int(parts[2]),
                        "accept": int(parts[3]),
                        "adjust": int(parts[4]),
                        "reject": int(parts[5]),
                        "dr": int(parts[6]),
                        "cr": int(parts[7]),
                        "fee": int(parts[8]),
                        "delta": int(parts[9]),
                        "check1": int(parts[10]),
                        "check2": int(parts[11]),
                    }
            
            return {"error": "Could not parse COBOL output"}
            
        except subprocess.TimeoutExpired:
            return {"error": "COOBOL engine timeout"}
        except Exception as e:
            return {"error": str(e)}
    
    def _run_python(self, data_dir: Path, out_dir: Path) -> Dict[str, Any]:
        """Run the Python reference implementation."""
        out_dir.mkdir(parents=True, exist_ok=True)
        
        start = time.perf_counter()
        try:
            stats = run_engine(data_dir, out_dir)
            wall_ms = int((time.perf_counter() - start) * 1000)
            stats["wall_ms"] = wall_ms
            return stats
        except Exception as e:
            return {"error": str(e)}
    
    def run(self, data_dir: Path, out_dir: Path) -> Dict[str, Any]:
        """Run the COBOL engine (native first, fallback to Python)."""
        if self.use_native and self.native_binary.exists():
            result = self._run_native(data_dir, out_dir)
            if "error" not in result:
                result["engine"] = "cobol-native"
                return result
            print(f"Native COBOL failed: {result['error']}, falling back to Python")
        
        result = self._run_python(data_dir, out_dir)
        result["engine"] = "cobol-python-reference"
        return result


def main():
    import argparse
    parser = argparse.ArgumentParser(description="COBOL Engine Adapter")
    parser.add_argument("--data-dir", type=Path, required=True, help="Input data directory")
    parser.add_argument("--out-dir", type=Path, required=True, help="Output directory")
    parser.add_argument("--native", action="store_true", help="Try native COBOL binary first")
    parser.add_argument("--evidence", type=Path, help="Output evidence file")
    parser.add_argument("--workload-id", default="cobol_batch", help="Workload ID")
    
    args = parser.parse_args()
    
    adapter = CobolAdapter(use_native=args.native)
    result = adapter.run(args.data_dir, args.out_dir)
    
    # Print result
    print(json.dumps(result, indent=2))

    if args.evidence:
        # Signed through armopt.evidence rather than re-derived here. The
        # previous local version had two defects at once: it hashed without
        # `separators=(",", ":")`, and it hashed the payload with an empty
        # "evidence_sha256" placeholder still inside it -- so the recorded
        # hash matched neither scheme and verify_evidence() always rejected
        # this file. Platform is also read from the host now instead of being
        # hardcoded to "Windows", which was simply false off Windows.
        from armopt.evidence import write_evidence as write_signed_evidence

        write_signed_evidence(
            args.evidence,
            results=result,
            workload_id=args.workload_id,
            adapter="cobol-batch",
        )
        print(f"Evidence written to {args.evidence}")


if __name__ == "__main__":
    main()