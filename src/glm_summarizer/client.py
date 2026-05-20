"""MaaS API client wrapping OpenAI SDK with session-affinity headers.

Key caching levers:
- X-Conversation-Id header: routes requests to the same inference instance
- httpx connection pool reuse: avoids repeated TLS handshakes
- Retry with exponential backoff: handles transient 429/503 errors
"""

from __future__ import annotations

import time
import logging
from typing import Iterator

import httpx
from openai import OpenAI, Stream
from openai.types.chat import ChatCompletion, ChatCompletionChunk

from .config import Config

logger = logging.getLogger(__name__)


class MaaSClient:
    """OpenAI-compatible client pre-configured for Huawei Cloud MaaS."""

    def __init__(self, config: Config):
        self.config = config
        self._http_client = httpx.Client(
            timeout=httpx.Timeout(120.0, connect=10.0),
            limits=httpx.Limits(
                max_keepalive_connections=config.concurrency + 2,
                max_connections=config.concurrency + 5,
                keepalive_expiry=30.0,
            ),
        )
        self._openai = OpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            http_client=self._http_client,
        )

    def _build_extra_headers(self, conversation_id: str | None) -> dict[str, str]:
        """Build extra headers for session affinity."""
        headers = dict(self.config.extra_headers)
        if conversation_id:
            headers["X-Conversation-Id"] = conversation_id
        return headers

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        conversation_id: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
        stream: bool = False,
    ) -> ChatCompletion:
        """Send a chat completion request."""
        extra_headers = self._build_extra_headers(conversation_id)

        kwargs = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": max_tokens or self.config.max_tokens,
            "temperature": temperature or self.config.temperature,
            "extra_headers": extra_headers,
        }

        last_exception = None
        for attempt in range(3):
            try:
                return self._openai.chat.completions.create(**kwargs)
            except self._openai.RateLimitError:
                if attempt < 2:
                    wait = 2**attempt * 1.0
                    logger.warning("Rate limited, retrying in %.1fs (attempt %d)", wait, attempt + 1)
                    time.sleep(wait)
                    continue
                raise
            except self._openai.APIConnectionError:
                if attempt < 2:
                    wait = 2**attempt * 0.5
                    logger.warning("Connection error, retrying in %.1fs (attempt %d)", wait, attempt + 1)
                    time.sleep(wait)
                    continue
                raise
            except self._openai.APIStatusError as e:
                if e.status_code >= 500 and attempt < 2:
                    wait = 2**attempt * 1.0
                    logger.warning("Server error %d, retrying in %.1fs (attempt %d)", e.status_code, wait, attempt + 1)
                    time.sleep(wait)
                    continue
                raise

    def chat_stream(
        self,
        messages: list[dict[str, str]],
        *,
        conversation_id: str | None = None,
        max_tokens: int | None = None,
        temperature: float | None = None,
    ) -> Iterator[ChatCompletionChunk]:
        """Send a streaming chat completion request."""
        extra_headers = self._build_extra_headers(conversation_id)

        kwargs = {
            "model": self.config.model,
            "messages": messages,
            "max_tokens": max_tokens or self.config.max_tokens,
            "temperature": temperature or self.config.temperature,
            "extra_headers": extra_headers,
            "stream": True,
        }

        last_exception = None
        for attempt in range(3):
            try:
                stream: Stream[ChatCompletionChunk] = self._openai.chat.completions.create(**kwargs)
                for chunk in stream:
                    yield chunk
                return
            except self._openai.RateLimitError:
                if attempt < 2:
                    time.sleep(2**attempt * 1.0)
                    continue
                raise
            except self._openai.APIConnectionError:
                if attempt < 2:
                    time.sleep(2**attempt * 0.5)
                    continue
                raise

    def close(self):
        self._http_client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
