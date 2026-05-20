"""Tests for summarizer (offline — no API calls)."""

import tempfile
from pathlib import Path

import pytest

from glm_summarizer.config import Config
from glm_summarizer.summarizer import Summarizer, _read_file, _extract_usage
from glm_summarizer.templates import get_template


class TestHelpers:
    def test_read_file_utf8(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
            f.write("# coding: utf-8\ndef hello(): return '你好'\n")
            path = f.name
        try:
            content = _read_file(path)
            assert "def hello()" in content
            assert "你好" in content
        finally:
            Path(path).unlink()

    def test_read_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            _read_file("/nonexistent/file.py")


class TestSummarizerInit:
    def test_requires_api_key(self):
        with pytest.raises(ValueError, match="api_key"):
            Summarizer(Config(api_key=""))

    def test_creates_with_key(self):
        # API key present, no validation error
        s = Summarizer(Config(api_key="test-key"))
        assert s.config.api_key == "test-key"
        s.close()


class TestBatchStats:
    def test_defaults(self):
        from glm_summarizer.summarizer import BatchStats
        bs = BatchStats(total=10)
        assert bs.total == 10
        assert bs.succeeded == 0
        assert bs.avg_prompt_tokens == 0.0
        assert bs.tokens_per_second == 0.0
