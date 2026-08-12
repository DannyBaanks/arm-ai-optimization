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

    def test_high_cost_weight_actually_wins_when_units_differ_wildly(self) -> None:
        # Dollar costs (~0.01-1.00) and millisecond latencies (~10-500) live
        # on wildly different raw scales. Before normalization, no
        # reachable cost_weight could make cost the deciding factor here --
        # the latency gap alone (500 vs 10) swamped the sum regardless of
        # weight. A user who sets cost_weight=100 expects cost to actually
        # matter.
        fast_expensive = NamedDemoAdapter("fast-expensive")
        slow_cheap = NamedDemoAdapter("slow-cheap")
        scheduler = CostLatencyScheduler(
            [
                BackendProfile(fast_expensive, mean_latency_ms=10, output_tokens_per_second=100,
                                cost_per_1k_tokens=1.00),
                BackendProfile(slow_cheap, mean_latency_ms=500, output_tokens_per_second=100,
                                cost_per_1k_tokens=0.01),
            ],
            cost_weight=100.0,
        )
        adapter, decision = scheduler.choose()
        self.assertEqual(adapter.name, "slow-cheap")
        self.assertEqual(decision.adapter, "slow-cheap")

    def test_single_profile_does_not_divide_by_zero(self) -> None:
        only = NamedDemoAdapter("only")
        scheduler = CostLatencyScheduler([
            BackendProfile(only, mean_latency_ms=42, output_tokens_per_second=7, cost_per_1k_tokens=0.5),
        ])
        adapter, decision = scheduler.choose()
        self.assertEqual(adapter.name, "only")
        self.assertEqual(decision.score, 0.0)

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
