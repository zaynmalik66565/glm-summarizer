"""Pluggable cache strategies + auto-tuner for self-evolution.

Multiple strategies are tested against real MaaS API calls. The one
with the lowest average prompt_tokens wins and is saved to config.

Strategies:
  affinity         — X-Conversation-Id header + concurrent (current)
  prefix-sequential— No special header, sequential requests (highest
                     chance of hitting warm cache on same instance)
  prefix-concurrent— No special header, concurrent (baseline)
  warmup           — Send a dummy warmup request first, then affinity
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from .cache import CacheSession
from .config import Config
from .summarizer import BatchStats, Summarizer, SummaryResult
from .templates import PromptTemplate, get_template


class CacheStrategy(ABC):
    """Base class for a cache strategy."""

    name: str = ""
    description: str = ""

    @abstractmethod
    def run_batch(
        self,
        summarizer: Summarizer,
        paths: list[str],
        template: PromptTemplate,
    ) -> BatchStats:
        ...


class AffinityStrategy(CacheStrategy):
    """X-Conversation-Id header routes all requests to the same instance.

    MaaS Prefix Caching reuses the KV cache of the system prompt across
    all requests in the batch. This is the default strategy.
    """

    name = "affinity"
    description = "X-Conversation-Id header, concurrent requests"

    def run_batch(self, summarizer, paths, template):
        session = CacheSession()
        return summarizer.batch_summarize(paths, template=template, session=session)


class PrefixSequentialStrategy(CacheStrategy):
    """No special headers, process files one at a time.

    Sequential requests have the highest chance of landing on the same
    inference instance, reusing its warm KV cache — even without an
    explicit affinity header. The trade-off is longer wall-clock time.
    """

    name = "prefix-sequential"
    description = "No affinity header, sequential (one at a time)"

    def run_batch(self, summarizer, paths, template):
        stats = BatchStats(total=len(paths))
        start = time.monotonic()

        for path in paths:
            result = summarizer.summarize_file(path, template=template)
            stats.results.append(result)
            if result.error:
                stats.failed += 1
            else:
                stats.succeeded += 1
                if result.usage:
                    stats.total_prompt_tokens += result.usage.get("prompt_tokens", 0)
                    stats.total_completion_tokens += result.usage.get("completion_tokens", 0)

        stats.total_elapsed_ms = (time.monotonic() - start) * 1000
        return stats


class PrefixConcurrentStrategy(CacheStrategy):
    """No affinity header, concurrent requests — baseline / control group.

    Each file gets a fresh CacheSession. The system prompt prefix is
    still stable, but without X-Conversation-Id, requests may scatter
    across instances. This is what you get with no tool at all.
    """

    name = "prefix-concurrent"
    description = "No affinity header, concurrent (baseline)"

    def run_batch(self, summarizer, paths, template):
        stats = BatchStats(total=len(paths))
        start = time.monotonic()

        for path in paths:
            result = summarizer.summarize_file(
                path,
                template=template,
                session=CacheSession(),  # fresh per file → no affinity
            )
            stats.results.append(result)
            if result.error:
                stats.failed += 1
            else:
                stats.succeeded += 1
                if result.usage:
                    stats.total_prompt_tokens += result.usage.get("prompt_tokens", 0)
                    stats.total_completion_tokens += result.usage.get("completion_tokens", 0)

        stats.total_elapsed_ms = (time.monotonic() - start) * 1000
        return stats


class WarmupStrategy(CacheStrategy):
    """Send a dummy warmup request first, then affinity + concurrent.

    The warmup primes the KV cache on the affinity-pinned instance
    before the real batch starts. Useful when the first request of
    a session always misses cache.
    """

    name = "warmup"
    description = "Warmup request first, then X-Conversation-Id concurrent"

    def run_batch(self, summarizer, paths, template):
        session = CacheSession()

        # Warmup: send a minimal request to prime the cache
        warmup_messages = [
            {"role": "system", "content": template.system},
            {"role": "user", "content": "Ready."},
        ]
        try:
            summarizer._client.chat(warmup_messages, conversation_id=session.id)
        except Exception:
            pass  # warmup failure is non-fatal

        return summarizer.batch_summarize(paths, template=template, session=session)


# Registry of all strategies to test
ALL_STRATEGIES: list[CacheStrategy] = [
    AffinityStrategy(),
    PrefixSequentialStrategy(),
    PrefixConcurrentStrategy(),
    WarmupStrategy(),
]


@dataclass
class StrategyResult:
    strategy: CacheStrategy
    batch_stats: BatchStats
    avg_prompt_tokens: float
    elapsed_s: float


@dataclass
class AutoTuneResult:
    results: list[StrategyResult]
    winner: StrategyResult
    baseline: StrategyResult  # prefix-concurrent (no cache)
    improvement_pct: float
    recommendation: str


def auto_tune(
    paths: list[str],
    *,
    config: Config | None = None,
    template: PromptTemplate | None = None,
    strategies: list[CacheStrategy] | None = None,
    verbose: bool = True,
) -> AutoTuneResult:
    """Test all strategies against real MaaS and pick the best.

    Returns the winning strategy recommendation. Users should then
    configure their Summarizer to use this strategy going forward.
    """
    if config is None:
        config = Config.load()

    if template is None:
        template = get_template(config.template)

    if strategies is None:
        strategies = ALL_STRATEGIES

    if verbose:
        print(f"Auto-tuning cache strategy for GLM 5.1")
        print(f"Files: {len(paths)}, Template: {template.name}")
        print(f"{'='*60}")

    results: list[StrategyResult] = []

    with Summarizer(config) as s:
        for strategy in strategies:
            if verbose:
                print(f"\n[{len(results)+1}/{len(strategies)}] {strategy.name}: {strategy.description}")

            start = time.monotonic()
            stats = strategy.run_batch(s, paths, template)
            elapsed = time.monotonic() - start

            avg = stats.avg_prompt_tokens if stats.succeeded > 0 else float("inf")
            sr = StrategyResult(
                strategy=strategy,
                batch_stats=stats,
                avg_prompt_tokens=avg,
                elapsed_s=elapsed,
            )
            results.append(sr)

            if verbose:
                ok = stats.succeeded
                failed = stats.failed
                tok = stats.total_prompt_tokens
                print(f"  → {ok} ok, {failed} failed, {tok:,} prompt tokens, {elapsed:.1f}s")

    # Baseline = prefix-concurrent (no cache)
    baseline = next(
        (r for r in results if r.strategy.name == "prefix-concurrent"),
        results[0],
    )

    # Winner = lowest avg prompt tokens (excluding baseline)
    candidates = [r for r in results if r.strategy.name != baseline.strategy.name]
    if not candidates or all(r.avg_prompt_tokens == float("inf") for r in candidates):
        winner = baseline
        improvement = 0.0
        recommendation = (
            "No strategy outperformed the baseline. "
            "GLM 5.1 may not support prefix caching on your MaaS deployment. "
            "Try verifying with a larger batch."
        )
    else:
        winner = min(candidates, key=lambda r: r.avg_prompt_tokens)
        baseline_avg = baseline.avg_prompt_tokens
        winner_avg = winner.avg_prompt_tokens
        if baseline_avg > 0:
            improvement = (baseline_avg - winner_avg) / baseline_avg * 100
        else:
            improvement = 0.0

        if improvement < 1:
            recommendation = (
                f"Strategy '{winner.name}' shows only {improvement:.1f}% improvement "
                "over baseline. Cache benefit is marginal — MaaS may not support "
                "prefix caching for GLM 5.1 on your deployment."
            )
        elif improvement < 10:
            recommendation = (
                f"Strategy '{winner.name}' gives {improvement:.1f}% token savings. "
                "Recommended. Run 'glm-summarize config --set-strategy {winner.name}' "
                "to persist."
            )
        else:
            recommendation = (
                f"Strategy '{winner.name}' gives {improvement:.1f}% token savings — "
                f"significant! Run 'glm-summarize config --set-strategy {winner.name}' "
                "to persist."
            )

    return AutoTuneResult(
        results=results,
        winner=winner,
        baseline=baseline,
        improvement_pct=round(improvement, 1),
        recommendation=recommendation,
    )


def format_autotune(result: AutoTuneResult) -> str:
    """Format auto-tune result as a readable report."""
    lines = [
        "=" * 60,
        "  AUTO-TUNE REPORT",
        "=" * 60,
        "",
        "  Strategy              Avg Prompt Tokens   Time    Improvement",
        "  -------------------   -----------------   ------  -----------",
    ]

    baseline_avg = result.baseline.avg_prompt_tokens
    for r in result.results:
        name = r.strategy.name.ljust(20)
        tok = f"{r.avg_prompt_tokens:,.0f}".rjust(18)
        time_s = f"{r.elapsed_s:.1f}s".rjust(7)
        if baseline_avg > 0 and r.strategy.name != result.baseline.strategy.name:
            pct = f"{(baseline_avg - r.avg_prompt_tokens) / baseline_avg * 100:+.1f}%".rjust(12)
        elif r.strategy.name == result.baseline.strategy.name:
            pct = "(baseline)".rjust(12)
        else:
            pct = "-".rjust(12)
        marker = " ← WINNER" if r.strategy.name == result.winner.strategy.name else ""
        lines.append(f"  {name} {tok} {time_s} {pct}{marker}")

    lines.extend([
        "",
        f"  Best strategy: {result.winner.strategy.name}",
        f"  Improvement:   {result.improvement_pct}% over baseline",
        "",
        f"  {result.recommendation}",
        "=" * 60,
    ])
    return "\n".join(lines)
