from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from armopt import menu
from armopt.evidence import verify_evidence, write_evidence


class DiscoveryTests(unittest.TestCase):
    def test_discovers_only_signed_evidence(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_evidence(directory / "signed.json", results={"a": 1},
                            workload_id="w", adapter="demo-adapter")
            (directory / "stdout_capture.json").write_text(json.dumps({"a": 1}), encoding="utf-8")
            (directory / "not_json.json").write_text("{broken", encoding="utf-8")

            found = menu.discover_evidence([directory])
        self.assertEqual([p.name for p in found], ["signed.json"])

    def test_is_decision_distinguishes_benchmark_from_selection(self) -> None:
        benchmark_payload = {"results": {"baseline": {}, "dataflow": {}, "speedup_wall": 1.0}}
        decision_payload = {"results": {"selected": "x", "candidates": [], "reason": "r"}}
        self.assertFalse(menu.is_decision(benchmark_payload))
        self.assertTrue(menu.is_decision(decision_payload))

    def test_discover_decisions_filters_to_selection_files_only(self) -> None:
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            write_evidence(directory / "bench.json", results={"baseline": {}, "dataflow": {}},
                            workload_id="w", adapter="demo-adapter")
            write_evidence(directory / "decision.json",
                            results={"selected": "demo-adapter", "candidates": [], "reason": "r"},
                            workload_id="scheduler-selection", adapter="demo-adapter")

            decisions = menu.discover_decisions([directory])
        self.assertEqual([p.name for p in decisions], ["decision.json"])


class ReachabilityTests(unittest.TestCase):
    def test_unreachable_provider_returns_false_quickly(self) -> None:
        # Port 1 is reserved/unassigned; nothing should ever be listening.
        dead = menu.Provider("dead", "ollama", "http://127.0.0.1:1", "/api/tags")
        self.assertFalse(menu.is_reachable(dead, timeout=0.5))


class FullPipelineBuildingBlocksTests(unittest.TestCase):
    """Exercises the exact sequence action_full_pipeline drives --
    benchmark -> evidence -> verification -> scheduler -> decision -- using
    the demo adapter so it's fast and has no network dependency. This is
    the product's core promise; it must actually work end to end, not just
    in the interactive menu."""

    def test_benchmark_to_decision_pipeline_is_real_and_verifiable(self) -> None:
        from armopt import cli as armopt_cli
        from armopt import select as armopt_select

        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            evidence_a = directory / "a.json"
            evidence_b = directory / "b.json"

            outcome_a = armopt_cli.run([
                "--demo", "--requests", "6", "--workers", "1", "--mode", "both",
                "--evidence", str(evidence_a),
            ])
            outcome_b = armopt_cli.run([
                "--demo", "--requests", "6", "--workers", "3", "--mode", "both",
                "--evidence", str(evidence_b),
            ])
            self.assertEqual(outcome_a["evidence_path"], evidence_a)
            self.assertEqual(outcome_b["evidence_path"], evidence_b)

            for path in (evidence_a, evidence_b):
                ok, message = verify_evidence(path)
                self.assertTrue(ok, message)

            decision = armopt_select.run(["--evidence", str(evidence_a), "--evidence", str(evidence_b)])
            self.assertIn(decision["selected"], {
                json.loads(evidence_a.read_text())["adapter"],
                json.loads(evidence_b.read_text())["adapter"],
            })

            decision_path = directory / "decision.json"
            write_evidence(decision_path, results=decision, workload_id="scheduler-selection",
                            adapter=decision["selected"])
            ok, message = verify_evidence(decision_path)
            self.assertTrue(ok, message)

            found = menu.discover_evidence([directory])
            self.assertEqual(len(found), 3)
            decisions = menu.discover_decisions([directory])
            self.assertEqual([p.name for p in decisions], ["decision.json"])


if __name__ == "__main__":
    unittest.main()
