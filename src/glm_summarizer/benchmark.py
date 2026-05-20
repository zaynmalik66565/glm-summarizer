"""Benchmark — A/B test cache effectiveness and calculate cost savings.

Compares two runs of the same files:
  Run A: with CacheSession + X-Conversation-Id (cache-enabled)
  Run B: without session (no X-Conversation-Id header)

MaaS GLM-5.1 pricing (华为云 MaaS, CNY per 1M tokens):
  Input:  ¥4.0  (cache miss) / ¥1.0  (cache hit)
  Output: ¥8.0
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from .cache import CacheSession
from .client import MaaSClient
from .config import Config
from .summarizer import BatchStats, Summarizer, _read_file
from .templates import PromptTemplate, get_template

# MaaS GLM-5.1 pricing — adjust if pricing changes
PRICING = {
    "input_per_1m": 4.0,       # ¥4.0 per 1M input tokens (cache miss)
    "cached_input_per_1m": 1.0, # ¥1.0 per 1M input tokens (cache hit)
    "output_per_1m": 8.0,      # ¥8.0 per 1M output tokens
}


@dataclass
class CostEstimate:
    """Cost breakdown for a batch run."""
    input_tokens: int
    output_tokens: int
    estimated_cache_hit_rate: float = 0.0  # 0.0-1.0

    @property
    def cached_input_tokens(self) -> int:
        return int(self.input_tokens * self.estimated_cache_hit_rate)

    @property
    def uncached_input_tokens(self) -> int:
        return self.input_tokens - self.cached_input_tokens

    @property
    def input_cost(self) -> float:
        cached_cost = (self.cached_input_tokens / 1_000_000) * PRICING["cached_input_per_1m"]
        uncached_cost = (self.uncached_input_tokens / 1_000_000) * PRICING["input_per_1m"]
        return cached_cost + uncached_cost

    @property
    def output_cost(self) -> float:
        return (self.output_tokens / 1_000_000) * PRICING["output_per_1m"]

    @property
    def total_cost(self) -> float:
        return self.input_cost + self.output_cost


@dataclass
class BenchmarkResult:
    """Side-by-side comparison of cached vs non-cached runs."""
    total_files: int
    with_cache: BatchStats
    without_cache: BatchStats

    @property
    def prompt_tokens_saved(self) -> int:
        """Estimated prompt tokens saved by caching."""
        if self.with_cache.succeeded == 0:
            return 0
        diff = (self.without_cache.total_prompt_tokens
                - self.with_cache.total_prompt_tokens)
        return max(0, diff)

    @property
    def cache_hit_rate(self) -> float:
        """Estimated cache hit rate from token savings."""
        if self.without_cache.total_prompt_tokens == 0:
            return 0.0
        return self.prompt_tokens_saved / self.without_cache.total_prompt_tokens

    @property
    def cost_without_cache(self) -> CostEstimate:
        return CostEstimate(
            input_tokens=self.without_cache.total_prompt_tokens,
            output_tokens=self.without_cache.total_completion_tokens,
            estimated_cache_hit_rate=0.0,
        )

    @property
    def cost_with_cache(self) -> CostEstimate:
        return CostEstimate(
            input_tokens=self.with_cache.total_prompt_tokens,
            output_tokens=self.with_cache.total_completion_tokens,
            estimated_cache_hit_rate=self.cache_hit_rate,
        )

    @property
    def cost_saved(self) -> float:
        return self.cost_without_cache.total_cost - self.cost_with_cache.total_cost

    @property
    def cost_saved_pct(self) -> float:
        denom = max(self.cost_without_cache.total_cost, 0.0001)
        return self.cost_saved / denom * 100


def _run_batch(
    summarizer: Summarizer,
    paths: list[str],
    template: PromptTemplate,
    use_cache: bool,
) -> BatchStats:
    """Run a batch, with or without cache session."""
    if use_cache:
        session = CacheSession()
        return summarizer.batch_summarize(paths, template=template, session=session)
    else:
        # Pass a fresh session per file — no X-Conversation-Id reuse
        stats = BatchStats(total=len(paths))
        start = time.monotonic()

        for path in paths:
            result = summarizer.summarize_file(
                path,
                template=template,
                session=CacheSession(),  # fresh session = no affinity
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


def run_benchmark(
    paths: list[str],
    *,
    config: Config | None = None,
    template: PromptTemplate | None = None,
) -> BenchmarkResult:
    """Run A/B benchmark comparing cached vs non-cached summarization."""
    if config is None:
        config = Config.load()

    if template is None:
        template = get_template(config.template)

    print(f"Benchmarking {len(paths)} files with template '{template.name}'")
    print(f"{'='*50}")

    with Summarizer(config) as s:
        print("\n[1/2] Running WITH cache session (X-Conversation-Id)...")
        with_cache = _run_batch(s, paths, template, use_cache=True)
        print(f"  → {with_cache.succeeded} ok, {with_cache.total_prompt_tokens:,} prompt tokens")

        print("\n[2/2] Running WITHOUT cache session...")
        without_cache = _run_batch(s, paths, template, use_cache=False)
        print(f"  → {without_cache.succeeded} ok, {without_cache.total_prompt_tokens:,} prompt tokens")

    return BenchmarkResult(
        total_files=len(paths),
        with_cache=with_cache,
        without_cache=without_cache,
    )


def format_benchmark(result: BenchmarkResult) -> str:
    """Format benchmark result as a readable report."""
    lines = [
        "=" * 60,
        "  CACHE BENCHMARK REPORT",
        "=" * 60,
        f"  Files tested:         {result.total_files}",
        "",
        "  --- Token Usage ---",
        f"  With cache:           {result.with_cache.total_prompt_tokens:,} prompt tokens",
        f"  Without cache:        {result.without_cache.total_prompt_tokens:,} prompt tokens",
        f"  Estimated saved:      {result.prompt_tokens_saved:,} tokens",
        f"  Cache hit rate:       {result.cache_hit_rate*100:.1f}%",
        "",
        "  --- Cost (GLM-5.1 MaaS pricing) ---",
        f"  Without cache:        ¥{result.cost_without_cache.total_cost:.4f}",
        f"  With cache:           ¥{result.cost_with_cache.total_cost:.4f}",
        f"  Saved:                ¥{result.cost_saved:.4f} ({result.cost_saved_pct:.1f}%)",
        "",
        "  --- Projection ---",
        f"  Per 100 files:        ~¥{result.cost_saved / max(result.total_files, 1) * 100:.2f} saved",
        f"  Per 1000 files:       ~¥{result.cost_saved / max(result.total_files, 1) * 1000:.2f} saved",
        "=" * 60,
    ]
    return "\n".join(lines)
