from __future__ import annotations

import unittest

from armopt.cli import DemoAdapter
from armopt.scheduler import BackendProfile, CostLatencyScheduler


class NamedDemoAdapter(DemoAdapter):
    def __init__(self, name: str) -> None:
        self.name = name


class SchedulerTests(unittest.TestCase):
    def test_scheduler_selects_lowest_weighted_profile(self) -> None:
        cheap = NamedDemoAdapter("cheap")
        fast = NamedDemoAdapter("fast")
        scheduler = CostLatencyScheduler([
            BackendProfile(cheap, mean_latency_ms=20, output_tokens_per_second=10,
                            cost_per_1k_tokens=0.01),
            BackendProfile(fast, mean_latency_ms=2, output_tokens_per_second=40,
                            cost_per_1k_tokens=0.20),
        ])
        adapter, decision = scheduler.choose()
        self.assertEqual(adapter.name, "fast")
        self.assertEqual(decision.adapter, "fast")

    def test_scheduler_infers_through_selected_adapter(self) -> None:
        adapter = NamedDemoAdapter("only")
        scheduler = CostLatencyScheduler([
            BackendProfile(adapter, 1, 10, 0),
        ])
        response, decision = scheduler.infer("hello", max_tokens=8)
        self.assertEqual(decision.adapter, "only")
        self.assertEqual(response.text, "hello")


if __name__ == "__main__":
    unittest.main()
