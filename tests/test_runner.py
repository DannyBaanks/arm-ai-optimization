from __future__ import annotations

import unittest

from armopt.cli import DemoAdapter
from armopt.contracts import Workload
from armopt.runner import compare_modes, run_benchmark


class RunnerTests(unittest.TestCase):
    def test_sequential_and_parallel_are_adapter_neutral(self) -> None:
        workload = Workload(["one two", "three four", "five six"])
        sequential = run_benchmark(DemoAdapter(), workload, workers=1)
        parallel = run_benchmark(
            DemoAdapter(), workload, workers=2, mode="dataflow"
        )
        self.assertEqual(sequential.requests, 3)
        self.assertEqual(parallel.requests, 3)
        self.assertEqual(sequential.output_tokens, parallel.output_tokens)
        self.assertGreater(sequential.tokens_per_second, 0)
        self.assertGreater(parallel.tokens_per_second, 0)

    def test_compare_modes_uses_same_workload(self) -> None:
        workload = Workload(["one", "two"])
        result = compare_modes(DemoAdapter(), workload, workers=2)
        self.assertEqual(result["baseline"]["requests"], 2)
        self.assertEqual(result["dataflow"]["requests"], 2)
        self.assertIn("speedup_wall", result)


if __name__ == "__main__":
    unittest.main()
