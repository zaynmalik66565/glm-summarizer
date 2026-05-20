"""Prompt templates for code summarization.

Templates use {variable} substitution syntax.
The system prompt portion is kept stable for cache friendliness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import yaml


@dataclass
class PromptTemplate:
    name: str
    description: str
    system: str
    user: str  # template with {code}, {path}, {language} placeholders


BUILTIN_TEMPLATES: dict[str, PromptTemplate] = {
    "file-summary": PromptTemplate(
        name="file-summary",
        description="Summarize a single source file: purpose, structure, key functions, and notable patterns.",
        system=(
            "You are an expert software engineer performing code review and documentation. "
            "Your task is to produce concise, accurate summaries of source code.\n\n"
            "Guidelines:\n"
            "- Focus on the code's purpose, architecture, and key design decisions.\n"
            "- List the main public functions/classes and their responsibilities.\n"
            "- Note any notable patterns, anti-patterns, or potential issues.\n"
            "- Keep the summary under 500 words unless the code is very large.\n"
            "- Use the same language as the input code for any technical terms."
        ),
        user=(
            "Summarize the following {language} code from file `{path}`.\n\n"
            "Include:\n"
            "1. Overall purpose (1 sentence)\n"
            "2. Key functions/classes and their roles\n"
            "3. Dependencies and imports overview\n"
            "4. Notable patterns or potential issues\n\n"
            "```{language}\n{code}\n```"
        ),
    ),
    "pr-diff": PromptTemplate(
        name="pr-diff",
        description="Summarize a git diff or pull request changeset.",
        system=(
            "You are an expert software engineer reviewing a pull request. "
            "Your task is to summarize code changes concisely and accurately.\n\n"
            "Guidelines:\n"
            "- Describe WHAT changed and WHY (infer the intent from the diff).\n"
            "- Group related changes together.\n"
            "- Flag any risky or breaking changes.\n"
            "- Keep the summary actionable and under 400 words."
        ),
        user=(
            "Summarize the following git diff from `{path}`.\n\n"
            "Include:\n"
            "1. High-level summary of changes (1-2 sentences)\n"
            "2. Files modified and what changed in each\n"
            "3. Any breaking changes or risks\n"
            "4. Suggested review focus areas\n\n"
            "```diff\n{code}\n```"
        ),
    ),
    "api-docs": PromptTemplate(
        name="api-docs",
        description="Generate API documentation from source code.",
        system=(
            "You are a technical writer specializing in API documentation. "
            "Your task is to generate clear, accurate API reference docs from source code.\n\n"
            "Guidelines:\n"
            "- Document every public function, class, and method.\n"
            "- Include parameter types, return types, and raised exceptions.\n"
            "- Write in a consistent style suitable for developer documentation.\n"
            "- Use Markdown formatting."
        ),
        user=(
            "Generate API documentation for the following {language} code from `{path}`.\n\n"
            "For each public API element, document:\n"
            "- Signature\n"
            "- Description of behavior\n"
            "- Parameters and return value\n"
            "- Any side effects or exceptions\n\n"
            "```{language}\n{code}\n```"
        ),
    ),
    "code-review": PromptTemplate(
        name="code-review",
        description="Review code for bugs, security issues, and style problems.",
        system=(
            "You are a senior software engineer performing a thorough code review. "
            "Be critical but constructive.\n\n"
            "Review dimensions:\n"
            "- Correctness: logic errors, off-by-one, null handling\n"
            "- Security: injection risks, auth bypass, data exposure\n"
            "- Performance: algorithmic complexity, unnecessary allocations\n"
            "- Maintainability: naming, coupling, testability\n"
            "- Style: consistency with language idioms"
        ),
        user=(
            "Review the following {language} code from `{path}`.\n\n"
            "Report findings organized by severity:\n"
            "- **Critical**: bugs or security vulnerabilities\n"
            "- **Warning**: performance issues, maintainability concerns\n"
            "- **Suggestion**: style improvements, minor optimizations\n\n"
            "```{language}\n{code}\n```"
        ),
    ),
}


def load_custom_templates(path: str) -> dict[str, PromptTemplate]:
    """Load custom templates from a YAML file.

    Expected format:
        templates:
          my-template:
            description: "..."
            system: "..."
            user: "..."
    """
    with open(path) as f:
        data = yaml.safe_load(f)

    templates: dict[str, PromptTemplate] = {}
    for name, spec in (data.get("templates") or {}).items():
        templates[name] = PromptTemplate(
            name=name,
            description=spec.get("description", ""),
            system=spec["system"],
            user=spec["user"],
        )
    return templates


def get_template(name: str, custom_path: str | None = None) -> PromptTemplate:
    """Get a template by name, falling back to builtins."""
    custom: dict[str, PromptTemplate] = {}
    if custom_path:
        custom = load_custom_templates(custom_path)

    if name in custom:
        return custom[name]
    if name in BUILTIN_TEMPLATES:
        return BUILTIN_TEMPLATES[name]

    available = list(BUILTIN_TEMPLATES) + list(custom)
    raise KeyError(f"Template '{name}' not found. Available: {', '.join(available)}")


def list_templates(custom_path: str | None = None) -> list[dict[str, str]]:
    """List all available templates with descriptions."""
    custom: dict[str, PromptTemplate] = {}
    if custom_path:
        custom = load_custom_templates(custom_path)

    result = []
    for name, t in {**BUILTIN_TEMPLATES, **custom}.items():
        result.append({"name": name, "description": t.description})
    return result
