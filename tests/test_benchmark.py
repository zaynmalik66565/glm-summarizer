"""Tests for benchmark and cost estimation (offline)."""

import pytest

from glm_summarizer.benchmark import (
    BenchmarkResult,
    CostEstimate,
    PRICING,
    format_benchmark,
)
from glm_summarizer.summarizer import BatchStats


class TestCostEstimate:
    def test_no_cache(self):
        ce = CostEstimate(
            input_tokens=1_000_000,
            output_tokens=500_000,
            estimated_cache_hit_rate=0.0,
        )
        # Input: 1M * ¥4.0/M = ¥4.00
        # Output: 0.5M * ¥8.0/M = ¥4.00
        assert ce.input_cost == pytest.approx(4.0)
        assert ce.output_cost == pytest.approx(4.0)
        assert ce.total_cost == pytest.approx(8.0)

    def test_full_cache(self):
        ce = CostEstimate(
            input_tokens=1_000_000,
            output_tokens=500_000,
            estimated_cache_hit_rate=1.0,
        )
        # All input cached: 1M * ¥1.0/M = ¥1.00
        assert ce.input_cost == pytest.approx(1.0)
        assert ce.output_cost == pytest.approx(4.0)
        assert ce.total_cost == pytest.approx(5.0)

    def test_partial_cache(self):
        ce = CostEstimate(
            input_tokens=1_000_000,
            output_tokens=0,
            estimated_cache_hit_rate=0.5,
        )
        # 500K cached (¥0.50) + 500K uncached (¥2.00) = ¥2.50
        assert ce.input_cost == pytest.approx(2.50)
        assert ce.cached_input_tokens == 500_000
        assert ce.uncached_input_tokens == 500_000


class TestBenchmarkResult:
    def test_properties(self):
        cached = BatchStats(
            total=5,
            succeeded=5,
            total_prompt_tokens=50_000,
            total_completion_tokens=5_000,
        )
        uncached = BatchStats(
            total=5,
            succeeded=5,
            total_prompt_tokens=55_000,
            total_completion_tokens=5_000,
        )
        result = BenchmarkResult(
            total_files=5,
            with_cache=cached,
            without_cache=uncached,
        )
        assert result.prompt_tokens_saved == 5000
        assert result.cache_hit_rate == pytest.approx(5000 / 55000)
        assert result.cost_with_cache.total_cost < result.cost_without_cache.total_cost

    def test_format(self):
        cached = BatchStats(total=3, succeeded=3, total_prompt_tokens=30000, total_completion_tokens=3000)
        uncached = BatchStats(total=3, succeeded=3, total_prompt_tokens=33000, total_completion_tokens=3000)
        result = BenchmarkResult(total_files=3, with_cache=cached, without_cache=uncached)
        report = format_benchmark(result)
        assert "CACHE BENCHMARK" in report
        assert "Cache hit rate" in report


class TestPricing:
    def test_pricing_values(self):
        assert PRICING["input_per_1m"] > 0
        assert PRICING["cached_input_per_1m"] > 0
        assert PRICING["output_per_1m"] > 0
        # Cached input should be cheaper than uncached
        assert PRICING["cached_input_per_1m"] < PRICING["input_per_1m"]
