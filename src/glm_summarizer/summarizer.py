"""Core summarization logic — single-file and batch with cache-aware batching."""

from __future__ import annotations

import asyncio
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from .cache import CacheSession
from .client import MaaSClient
from .config import Config
from .templates import PromptTemplate, get_template

logger = logging.getLogger(__name__)


@dataclass
class SummaryResult:
    path: str
    summary: str
    usage: dict | None = None
    error: str | None = None
    elapsed_ms: float = 0.0


@dataclass
class BatchStats:
    total: int = 0
    succeeded: int = 0
    failed: int = 0
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_elapsed_ms: float = 0.0
    cache_session: dict | None = None
    results: list[SummaryResult] = field(default_factory=list)

    @property
    def avg_prompt_tokens(self) -> float:
        if self.succeeded == 0:
            return 0.0
        return self.total_prompt_tokens / self.succeeded

    @property
    def tokens_per_second(self) -> float:
        if self.total_elapsed_ms == 0:
            return 0.0
        return (self.total_completion_tokens) / (self.total_elapsed_ms / 1000)


def _read_file(path: str) -> str:
    """Read a file, trying common encodings."""
    for enc in ("utf-8", "latin-1"):
        try:
            with open(path, encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    raise ValueError(f"Cannot decode {path}")


def _extract_usage(response) -> dict:
    """Extract token usage from a ChatCompletion response."""
    if hasattr(response, "usage") and response.usage:
        return {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }
    return {}


class Summarizer:
    """High-level summarization API with cache-aware session management."""

    def __init__(self, config: Config | None = None, **overrides):
        self.config = config or Config.load(**overrides)
        errors = self.config.validate()
        if errors:
            raise ValueError("\n".join(errors))
        self._client = MaaSClient(self.config)

    def summarize_file(
        self,
        path: str,
        *,
        template: PromptTemplate | None = None,
        session: CacheSession | None = None,
    ) -> SummaryResult:
        """Summarize a single file."""
        if template is None:
            template = get_template(self.config.template)

        start = time.monotonic()
        path_obj = Path(path)

        try:
            code = _read_file(str(path_obj))
        except Exception as e:
            return SummaryResult(path=str(path_obj), summary="", error=str(e))

        if session is None:
            session = CacheSession()

        messages = session.build_messages(
            template,
            code=code,
            path=str(path_obj),
        )

        try:
            response = self._client.chat(messages, conversation_id=session.id)
            summary = response.choices[0].message.content or ""
            usage = _extract_usage(response)
        except Exception as e:
            logger.error("Failed to summarize %s: %s", path, e)
            return SummaryResult(path=str(path_obj), summary="", error=str(e))

        elapsed = (time.monotonic() - start) * 1000
        return SummaryResult(path=str(path_obj), summary=summary, usage=usage, elapsed_ms=elapsed)

    def summarize_text(
        self,
        code: str,
        *,
        path: str = "inline",
        language: str = "",
        template: PromptTemplate | None = None,
        session: CacheSession | None = None,
    ) -> SummaryResult:
        """Summarize an arbitrary code snippet."""
        if template is None:
            template = get_template(self.config.template)

        start = time.monotonic()
        if session is None:
            session = CacheSession()

        messages = session.build_messages(
            template,
            code=code,
            path=path,
            language=language,
        )

        try:
            response = self._client.chat(messages, conversation_id=session.id)
            summary = response.choices[0].message.content or ""
            usage = _extract_usage(response)
        except Exception as e:
            return SummaryResult(path=path, summary="", error=str(e))

        elapsed = (time.monotonic() - start) * 1000
        return SummaryResult(path=path, summary=summary, usage=usage, elapsed_ms=elapsed)

    def batch_summarize(
        self,
        paths: list[str],
        *,
        template: PromptTemplate | None = None,
        session: CacheSession | None = None,
        progress: bool = True,
    ) -> BatchStats:
        """Summarize multiple files, sharing a cache session.

        Files are processed concurrently with a thread pool, all sharing
        the same CacheSession (and thus X-Conversation-Id).
        """
        if template is None:
            template = get_template(self.config.template)

        if session is None:
            session = CacheSession()

        stats = BatchStats(total=len(paths))
        start = time.monotonic()

        with ThreadPoolExecutor(max_workers=self.config.concurrency) as pool:
            futures = {
                pool.submit(self._summarize_one, p, template, session): p
                for p in paths
            }

            iterator = as_completed(futures)
            if progress:
                try:
                    from tqdm import tqdm
                    iterator = tqdm(iterator, total=len(paths), desc="Summarizing")
                except ImportError:
                    pass

            for future in iterator:
                result = future.result()
                stats.results.append(result)
                if result.error:
                    stats.failed += 1
                else:
                    stats.succeeded += 1
                    if result.usage:
                        stats.total_prompt_tokens += result.usage.get("prompt_tokens", 0)
                        stats.total_completion_tokens += result.usage.get("completion_tokens", 0)

        stats.total_elapsed_ms = (time.monotonic() - start) * 1000
        stats.cache_session = session.stats()
        return stats

    def _summarize_one(
        self,
        path: str,
        template: PromptTemplate,
        session: CacheSession,
    ) -> SummaryResult:
        """Worker for batch summarization — runs in thread pool."""
        return self.summarize_file(path, template=template, session=session)

    def close(self):
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
