"""Tests for cache strategies and auto-tuner (offline)."""

import pytest
from glm_summarizer.strategies import (
    AffinityStrategy,
    PrefixSequentialStrategy,
    PrefixConcurrentStrategy,
    WarmupStrategy,
    ALL_STRATEGIES,
    AutoTuneResult,
    StrategyResult,
    format_autotune,
)
from glm_summarizer.summarizer import BatchStats
from glm_summarizer.templates import get_template


class TestStrategies:
    def test_all_strategies_registered(self):
        assert len(ALL_STRATEGIES) >= 4
        names = {s.name for s in ALL_STRATEGIES}
        assert "affinity" in names
        assert "prefix-sequential" in names
        assert "prefix-concurrent" in names
        assert "warmup" in names

    def test_strategy_names_unique(self):
        names = [s.name for s in ALL_STRATEGIES]
        assert len(names) == len(set(names))

    def test_affinity_has_name(self):
        s = AffinityStrategy()
        assert s.name == "affinity"
        assert len(s.description) > 0

    def test_prefix_sequential_has_name(self):
        s = PrefixSequentialStrategy()
        assert s.name == "prefix-sequential"

    def test_prefix_concurrent_has_name(self):
        s = PrefixConcurrentStrategy()
        assert s.name == "prefix-concurrent"

    def test_warmup_has_name(self):
        s = WarmupStrategy()
        assert s.name == "warmup"


class TestAutoTuneResult:
    def test_properties(self):
        baseline = StrategyResult(
            strategy=PrefixConcurrentStrategy(),
            batch_stats=BatchStats(total=3, succeeded=3, total_prompt_tokens=6000),
            avg_prompt_tokens=2000,
            elapsed_s=3.0,
        )
        winner = StrategyResult(
            strategy=AffinityStrategy(),
            batch_stats=BatchStats(total=3, succeeded=3, total_prompt_tokens=4500),
            avg_prompt_tokens=1500,
            elapsed_s=2.0,
        )
        result = AutoTuneResult(
            results=[baseline, winner],
            winner=winner,
            baseline=baseline,
            improvement_pct=25.0,
            recommendation="Use affinity.",
        )
        assert result.improvement_pct == 25.0
        assert "Use affinity" in result.recommendation

    def test_format(self):
        baseline = StrategyResult(
            strategy=PrefixConcurrentStrategy(),
            batch_stats=BatchStats(total=2, succeeded=2),
            avg_prompt_tokens=5000,
            elapsed_s=2.0,
        )
        winner = StrategyResult(
            strategy=AffinityStrategy(),
            batch_stats=BatchStats(total=2, succeeded=2),
            avg_prompt_tokens=4000,
            elapsed_s=1.5,
        )
        result = AutoTuneResult(
            results=[baseline, winner],
            winner=winner,
            baseline=baseline,
            improvement_pct=20.0,
            recommendation="Use affinity.",
        )
        report = format_autotune(result)
        assert "AUTO-TUNE REPORT" in report
        assert "20.0%" in report
        assert "WINNER" in report
