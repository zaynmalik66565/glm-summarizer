"""Configuration management with multi-source resolution.

Priority: CLI args > env vars > config file > defaults
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

DEFAULT_BASE_URL = "https://api-ap-southeast-1.modelarts-maas.com/openai/v1"
DEFAULT_MODEL = "glm-5.1"
DEFAULT_MAX_TOKENS = 4096
DEFAULT_TEMPERATURE = 0.3
DEFAULT_CONCURRENCY = 5
DEFAULT_TEMPLATE = "file-summary"
DEFAULT_STRATEGY = "affinity"

CONFIG_FILE_NAME = ".glm-summarizer.yaml"
GLOBAL_CONFIG_DIR = Path.home() / ".glm-summarizer"
GLOBAL_CONFIG_FILE = GLOBAL_CONFIG_DIR / "config.yaml"

_ENV_MAP = {
    "api_key": "MAAS_API_KEY",
    "base_url": "MAAS_BASE_URL",
    "model": "MAAS_MODEL",
    "max_tokens": "MAAS_MAX_TOKENS",
    "temperature": "MAAS_TEMPERATURE",
    "concurrency": "MAAS_CONCURRENCY",
    "template": "MAAS_TEMPLATE",
    "strategy": "MAAS_STRATEGY",
}


def _find_project_config() -> Path | None:
    """Walk up from CWD to find the nearest .glm-summarizer.yaml."""
    cwd = Path.cwd()
    for parent in [cwd, *cwd.parents]:
        candidate = parent / CONFIG_FILE_NAME
        if candidate.exists():
            return candidate
    return None


def _load_yaml(path: Path) -> dict[str, Any]:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _load_env() -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, env_var in _ENV_MAP.items():
        val = os.environ.get(env_var)
        if val is not None:
            # Coerce numeric values
            if key in ("max_tokens", "concurrency"):
                try:
                    val = int(val)
                except ValueError:
                    continue
            elif key == "temperature":
                try:
                    val = float(val)
                except ValueError:
                    continue
            result[key] = val
    return result


@dataclass
class Config:
    api_key: str = ""
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    max_tokens: int = DEFAULT_MAX_TOKENS
    temperature: float = DEFAULT_TEMPERATURE
    concurrency: int = DEFAULT_CONCURRENCY
    template: str = DEFAULT_TEMPLATE
    strategy: str = DEFAULT_STRATEGY
    extra_headers: dict[str, str] = field(default_factory=dict)
    _source: str = "defaults"

    @classmethod
    def load(cls, **overrides: Any) -> "Config":
        """Load config from all sources, with optional overrides."""
        merged: dict[str, Any] = {}

        # Layer 1: global config file
        if GLOBAL_CONFIG_FILE.exists():
            merged.update(_load_yaml(GLOBAL_CONFIG_FILE))

        # Layer 2: project config file
        project_cfg = _find_project_config()
        if project_cfg:
            merged.update(_load_yaml(project_cfg))

        # Layer 3: environment variables
        env_cfg = _load_env()
        merged.update(env_cfg)

        # Layer 4: explicit overrides
        merged.update({k: v for k, v in overrides.items() if v is not None})

        # Normalize extra_headers
        extra_headers = merged.pop("extra_headers", {}) or {}

        cfg = cls(**{k: v for k, v in merged.items() if k in cls.__dataclass_fields__})
        cfg.extra_headers = extra_headers
        return cfg

    @property
    def headers(self) -> dict[str, str]:
        """HTTP headers for MaaS API requests."""
        h = {"Authorization": f"Bearer {self.api_key}"}
        h.update(self.extra_headers)
        return h

    def save(self, path: Path | None = None) -> Path:
        """Persist config to a YAML file.

        Args:
            path: Target path. Defaults to global config file.
        Returns:
            The path written to.
        """
        target = path or GLOBAL_CONFIG_FILE
        target.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "api_key": self.api_key,
            "base_url": self.base_url,
            "model": self.model,
            "max_tokens": self.max_tokens,
            "temperature": self.temperature,
            "concurrency": self.concurrency,
            "template": self.template,
            "strategy": self.strategy,
            "extra_headers": self.extra_headers,
        }
        with open(target, "w") as f:
            yaml.dump(data, f, allow_unicode=True, sort_keys=False)
        return target

    def validate(self) -> list[str]:
        """Check required fields; return list of missing items."""
        errors = []
        if not self.api_key:
            errors.append(
                "api_key is required. Set MAAS_API_KEY env var, "
                "or configure it in ~/.glm-summarizer/config.yaml"
            )
        return errors
