from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from armopt.scheduler import CostLatencyScheduler
from armopt.select import profile_from_evidence


def _write_evidence(directory: Path, name: str, *, mean_latency_ms: float,
                     tokens_per_second: float) -> Path:
    path = directory / name
    path.write_text(json.dumps({
        "schema": "armopt.evidence/1",
        "adapter": f"http:{name}",
        "results": {
            "baseline": {"mean_latency_ms": 1.0, "tokens_per_second": 1.0},
            "dataflow": {
                "mean_latency_ms": mean_latency_ms,
                "tokens_per_second": tokens_per_second,
            },
        },
    }), encoding="utf-8")
    return path


class ProfileFromEvidenceTests(unittest.TestCase):
    def test_reads_dataflow_figures_not_baseline(self) -> None:
        with TemporaryDirectory() as tmp:
            path = _write_evidence(Path(tmp), "run.json", mean_latency_ms=250.0,
                                    tokens_per_second=40.0)
            profile = profile_from_evidence(path, cost_per_1k_tokens=0.02)
        self.assertEqual(profile.adapter.name, "http:run.json")
        self.assertEqual(profile.mean_latency_ms, 250.0)
        self.assertEqual(profile.output_tokens_per_second, 40.0)
        self.assertEqual(profile.cost_per_1k_tokens, 0.02)

    def test_falls_back_to_flat_results_without_a_dataflow_key(self) -> None:
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "flat.json"
            path.write_text(json.dumps({
                "adapter": "demo-adapter",
                "results": {"mean_latency_ms": 5.0, "tokens_per_second": 900.0},
            }), encoding="utf-8")
            profile = profile_from_evidence(path)
        self.assertEqual(profile.mean_latency_ms, 5.0)
        self.assertEqual(profile.cost_per_1k_tokens, 0.0)

    def test_two_real_evidence_files_pick_the_faster_one(self) -> None:
        # Same shape as the Ollama-vs-llama-server evidence this repo
        # actually collected on Arm64 CI: llama-server measured faster
        # (lower mean_latency_ms), so it should win with equal costs.
        with TemporaryDirectory() as tmp:
            directory = Path(tmp)
            ollama = _write_evidence(directory, "ollama.json", mean_latency_ms=4315.46,
                                      tokens_per_second=50.897)
            llama_server = _write_evidence(directory, "llama_server.json",
                                            mean_latency_ms=8491.772, tokens_per_second=30.146)
            profiles = [profile_from_evidence(ollama), profile_from_evidence(llama_server)]
            scheduler = CostLatencyScheduler(profiles, cost_weight=0.0)
            adapter, decision = scheduler.choose()
        self.assertEqual(adapter.name, "http:ollama.json")
        self.assertEqual(decision.adapter, "http:ollama.json")


if __name__ == "__main__":
    unittest.main()
