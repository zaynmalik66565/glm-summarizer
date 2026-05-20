"""GLM Summarizer — High cache-hit-rate code summarization for Huawei Cloud MaaS."""

from .benchmark import BenchmarkResult, CostEstimate, PRICING, run_benchmark, format_benchmark
from .cache import CacheSession
from .client import MaaSClient
from .config import Config
from .summarizer import BatchStats, Summarizer, SummaryResult
from .templates import (
    PromptTemplate,
    get_template,
    list_templates,
    load_custom_templates,
)

__all__ = [
    "Config",
    "MaaSClient",
    "CacheSession",
    "Summarizer",
    "SummaryResult",
    "BatchStats",
    "BenchmarkResult",
    "CostEstimate",
    "run_benchmark",
    "format_benchmark",
    "PRICING",
    "PromptTemplate",
    "get_template",
    "list_templates",
    "load_custom_templates",
]
__version__ = "0.1.0"
