"""Cache strategy for maximizing KV-cache hit rate on MaaS.

Core principles:
1. Session-scoped conversation ID (X-Conversation-Id) routes all requests
   in a batch to the same inference instance so the server-side Prefix
   Caching can reuse the KV cache of the system prompt.
2. Each file is sent as an INDEPENDENT request sharing the same system
   prompt prefix — the prefix never changes, so the cache is always valid.
3. Prefix stability is validated before batch runs to catch config issues
   that would silently defeat caching.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field

from .templates import PromptTemplate


@dataclass
class PrefixDigest:
    """Tracks the hash of the system prompt prefix for cache validation."""

    system_hash: str
    """SHA256 of the system prompt text.  If this changes between requests,
    the KV cache is invalidated."""


def _hash(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


@dataclass
class CacheSession:
    """Manages a cache session for a batch of summarization requests.

    Usage::

        session = CacheSession()
        for file in files:
            messages = session.build_messages(template, code=..., path=...)
            client.chat(messages, conversation_id=session.id)
        print(session.stats())
    """

    id: str = field(default_factory=lambda: uuid.uuid4().hex)
    _system_hash: str | None = field(default=None, init=False)
    _request_count: int = field(default=0, init=False)
    _warnings: list[str] = field(default_factory=list, init=False)

    def build_messages(
        self,
        template: PromptTemplate,
        *,
        code: str,
        path: str = "",
        language: str = "",
    ) -> list[dict[str, str]]:
        """Build a messages list with stable system-prompt prefix.

        The system prompt is always the same within a session, so the server-side
        Prefix Caching can reuse its KV cache across all requests in the batch.
        """
        system = template.system
        current_hash = _hash(system)

        if self._system_hash is None:
            self._system_hash = current_hash
        elif self._system_hash != current_hash:
            self._warnings.append(
                f"Request {self._request_count + 1}: system prompt hash changed "
                f"({self._system_hash} -> {current_hash}). "
                "KV cache will be invalidated for this request."
            )
            self._system_hash = current_hash

        if not language:
            language = _guess_language(path)

        user = template.user.format(code=code, path=path, language=language)
        self._request_count += 1

        return [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ]

    @property
    def is_stable(self) -> bool:
        """Whether the prefix has been stable across all requests so far."""
        return len(self._warnings) == 0

    def stats(self) -> dict:
        """Return session statistics for observability."""
        return {
            "session_id": self.id,
            "requests": self._request_count,
            "prefix_stable": self.is_stable,
            "system_hash": self._system_hash or "",
            "warnings": list(self._warnings),
        }

    def check_prefix_health(self) -> list[str]:
        """Return warnings if the cache strategy might be compromised."""
        issues = list(self._warnings)
        if self._system_hash is None:
            issues.append("No requests sent yet — cannot verify prefix stability.")
        return issues


def _guess_language(path: str) -> str:
    """Guess language from file extension."""
    ext_map = {
        ".py": "python",
        ".js": "javascript",
        ".ts": "typescript",
        ".tsx": "typescript",
        ".jsx": "javascript",
        ".go": "go",
        ".rs": "rust",
        ".java": "java",
        ".cpp": "cpp",
        ".c": "c",
        ".h": "c",
        ".hpp": "cpp",
        ".rb": "ruby",
        ".php": "php",
        ".swift": "swift",
        ".kt": "kotlin",
        ".scala": "scala",
        ".sh": "bash",
        ".bash": "bash",
        ".zsh": "bash",
        ".sql": "sql",
        ".yaml": "yaml",
        ".yml": "yaml",
        ".json": "json",
        ".toml": "toml",
        ".md": "markdown",
        ".css": "css",
        ".html": "html",
        ".xml": "xml",
        ".vue": "vue",
        ".tf": "hcl",
        ".dockerfile": "dockerfile",
    }
    if path:
        import os
        ext = os.path.splitext(path)[1].lower()
        if ext in ext_map:
            return ext_map[ext]
        # Check full filename (e.g. Dockerfile, Makefile)
        fname = os.path.basename(path).lower()
        if fname in ext_map:
            return ext_map[fname]
    return ""
