"""Tests for config loading and resolution."""

import os
import tempfile
from pathlib import Path

import yaml
import pytest

from glm_summarizer.config import Config, _find_project_config, _load_env


class TestConfig:
    def test_defaults(self):
        cfg = Config()
        assert cfg.model == "glm-5.1"
        assert cfg.max_tokens == 4096
        assert cfg.temperature == 0.3
        assert cfg.concurrency == 5

    def test_overrides(self):
        cfg = Config.load(model="glm-5", max_tokens=2048)
        assert cfg.model == "glm-5"
        assert cfg.max_tokens == 2048

    def test_env_loading(self, monkeypatch):
        monkeypatch.setenv("MAAS_API_KEY", "test-key-123")
        monkeypatch.setenv("MAAS_MODEL", "glm-5.1")
        monkeypatch.setenv("MAAS_MAX_TOKENS", "8192")
        monkeypatch.setenv("MAAS_TEMPERATURE", "0.5")
        monkeypatch.setenv("MAAS_CONCURRENCY", "10")

        env = _load_env()
        assert env["api_key"] == "test-key-123"
        assert env["model"] == "glm-5.1"
        assert env["max_tokens"] == 8192
        assert env["temperature"] == 0.5
        assert env["concurrency"] == 10

    def test_validation_missing_key(self):
        cfg = Config(api_key="")
        errors = cfg.validate()
        assert len(errors) == 1
        assert "api_key" in errors[0]

    def test_validation_ok(self):
        cfg = Config(api_key="test-key")
        errors = cfg.validate()
        assert len(errors) == 0

    def test_global_config_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "glm_summarizer.config.GLOBAL_CONFIG_FILE",
            tmp_path / "config.yaml",
        )
        (tmp_path / "config.yaml").write_text("model: glm-5\ntemperature: 0.7\n")

        cfg = Config.load()
        assert cfg.model == "glm-5"
        assert cfg.temperature == 0.7
        # api_key still empty
        assert cfg.api_key == ""

    def test_override_wins_over_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            "glm_summarizer.config.GLOBAL_CONFIG_FILE",
            tmp_path / "config.yaml",
        )
        (tmp_path / "config.yaml").write_text("model: glm-5\n")

        cfg = Config.load(model="glm-5.1")
        assert cfg.model == "glm-5.1"  # override wins

    def test_headers_property(self):
        cfg = Config(api_key="test-key", extra_headers={"X-Foo": "bar"})
        h = cfg.headers
        assert h["Authorization"] == "Bearer test-key"
        assert h["X-Foo"] == "bar"
