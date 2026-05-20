"""CLI entry point — provides `glm-summarize` command."""

from __future__ import annotations

import glob
import json
import logging
import sys
from pathlib import Path
from typing import Optional

import typer

from .benchmark import run_benchmark, format_benchmark, PRICING
from .config import Config
from .summarizer import BatchStats, Summarizer, SummaryResult
from .templates import get_template, list_templates, load_custom_templates

app = typer.Typer(
    name="glm-summarize",
    help="High cache-hit-rate code summarization using GLM models on Huawei Cloud MaaS.",
)
templates_app = typer.Typer(help="Manage prompt templates.")
app.add_typer(templates_app, name="template")

logger = logging.getLogger(__name__)

# --- Shared options ---

_opt_model = typer.Option(None, "--model", "-m", help="Model ID (default: glm-5.1)")
_opt_api_key = typer.Option(None, "--api-key", "-k", help="MaaS API key")
_opt_base_url = typer.Option(None, "--base-url", help="MaaS base URL")
_opt_template_name = typer.Option(
    None, "--template", "-t", help="Prompt template name"
)
_opt_templates_path = typer.Option(
    None, "--templates", help="Path to custom templates YAML file"
)
_opt_max_tokens = typer.Option(None, "--max-tokens", help="Max output tokens")
_opt_temperature = typer.Option(None, "--temperature", help="Sampling temperature")
_opt_concurrency = typer.Option(None, "--concurrency", "-c", help="Number of parallel workers")
_opt_verbose = typer.Option(False, "--verbose", "-v", help="Verbose output")
_opt_output = typer.Option(None, "--output", "-o", help="Output file path")
_opt_format = typer.Option("json", "--format", "-f", help="Output format: json, markdown, text")


def _build_config(**overrides) -> Config:
    cfg = Config.load(**{k: v for k, v in overrides.items() if v is not None})
    errors = cfg.validate()
    if errors:
        typer.echo("\n".join(errors), err=True)
        raise typer.Exit(1)
    return cfg


def _print_result(result: SummaryResult, fmt: str):
    if fmt == "json":
        typer.echo(json.dumps({
            "path": result.path,
            "summary": result.summary,
            "usage": result.usage,
            "error": result.error,
            "elapsed_ms": round(result.elapsed_ms, 1),
        }, ensure_ascii=False, indent=2))
    elif fmt == "markdown":
        typer.echo(f"# {result.path}\n\n{result.summary}\n")
    else:
        typer.echo(f"=== {result.path} ===\n{result.summary}\n")


def _print_batch_stats(stats: BatchStats):
    typer.echo(f"\n{'='*60}")
    typer.echo(f"  Files: {stats.total} total, {stats.succeeded} ok, {stats.failed} failed")
    typer.echo(f"  Time:  {stats.total_elapsed_ms/1000:.1f}s")
    if stats.succeeded > 0:
        typer.echo(f"  Input tokens:  {stats.total_prompt_tokens:,}")
        typer.echo(f"  Output tokens: {stats.total_completion_tokens:,}")
        typer.echo(f"  Ratio:         {stats.total_prompt_tokens/max(stats.total_completion_tokens,1):.1f}:1")
        typer.echo(f"  Avg input/req: {stats.avg_prompt_tokens:,.0f}")
        typer.echo(f"  Speed:         {stats.tokens_per_second:.0f} tok/s")
        # Cost estimate
        input_cost = (stats.total_prompt_tokens / 1_000_000) * PRICING["input_per_1m"]
        output_cost = (stats.total_completion_tokens / 1_000_000) * PRICING["output_per_1m"]
        typer.echo(f"  Est. cost:     ¥{input_cost + output_cost:.4f}")
    if stats.cache_session:
        cs = stats.cache_session
        typer.echo(f"  Session:       {cs['session_id']}")
        typer.echo(f"  Prefix stable: {cs['prefix_stable']}")
    typer.echo(f"{'='*60}")


# --- Commands ---

@app.command()
def file(
    path: str = typer.Argument(..., help="Path to source file"),
    model: Optional[str] = _opt_model,
    api_key: Optional[str] = _opt_api_key,
    base_url: Optional[str] = _opt_base_url,
    template_name: Optional[str] = _opt_template_name,
    templates_path: Optional[str] = _opt_templates_path,
    max_tokens: Optional[int] = _opt_max_tokens,
    temperature: Optional[float] = _opt_temperature,
    verbose: bool = _opt_verbose,
    output: Optional[str] = _opt_output,
    fmt: str = _opt_format,
):
    """Summarize a single source file."""
    if verbose:
        logging.basicConfig(level=logging.INFO)

    cfg = _build_config(
        api_key=api_key,
        base_url=base_url,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
    )
    if template_name:
        cfg.template = template_name

    template = get_template(cfg.template, custom_path=templates_path)
    if verbose:
        typer.echo(f"Using template: {template.name}", err=True)

    with Summarizer(cfg) as s:
        result = s.summarize_file(path, template=template)

    if result.error:
        typer.echo(f"Error: {result.error}", err=True)
        raise typer.Exit(1)

    if output:
        Path(output).write_text(result.summary)
        typer.echo(f"Saved to {output}", err=True)
    else:
        _print_result(result, fmt)

    if verbose and result.usage:
        typer.echo(
            f"\nTokens: {result.usage['prompt_tokens']} in / "
            f"{result.usage['completion_tokens']} out "
            f"({result.elapsed_ms:.0f}ms)",
            err=True,
        )


@app.command()
def batch(
    glob_pattern: str = typer.Argument(..., help="File glob pattern, e.g. 'src/**/*.py'"),
    model: Optional[str] = _opt_model,
    api_key: Optional[str] = _opt_api_key,
    base_url: Optional[str] = _opt_base_url,
    template_name: Optional[str] = _opt_template_name,
    templates_path: Optional[str] = _opt_templates_path,
    max_tokens: Optional[int] = _opt_max_tokens,
    temperature: Optional[float] = _opt_temperature,
    concurrency: Optional[int] = _opt_concurrency,
    verbose: bool = _opt_verbose,
    output: Optional[str] = _opt_output,
    fmt: str = _opt_format,
):
    """Summarize multiple files matching a glob pattern.

    All files share the same cache session for maximum KV-cache reuse.
    """
    if verbose:
        logging.basicConfig(level=logging.INFO)

    cfg = _build_config(
        api_key=api_key,
        base_url=base_url,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        concurrency=concurrency,
    )
    if template_name:
        cfg.template = template_name

    template = get_template(cfg.template, custom_path=templates_path)
    if verbose:
        typer.echo(f"Using template: {template.name}", err=True)

    paths = sorted(glob.glob(glob_pattern, recursive=True))
    if not paths:
        typer.echo(f"No files matched: {glob_pattern}", err=True)
        raise typer.Exit(1)

    # Filter to regular files only
    paths = [p for p in paths if Path(p).is_file()]
    if verbose:
        typer.echo(f"Found {len(paths)} files", err=True)

    with Summarizer(cfg) as s:
        stats = s.batch_summarize(paths, template=template, progress=True)

    # Output results
    if output:
        out_dir = Path(output)
        out_dir.mkdir(parents=True, exist_ok=True)
        for r in stats.results:
            if not r.error:
                out_name = Path(r.path).stem + ".md"
                (out_dir / out_name).write_text(r.summary)
        typer.echo(f"\nSaved {stats.succeeded} summaries to {output}/", err=True)
    elif fmt == "json":
        typer.echo(json.dumps({
            "stats": {
                "total": stats.total,
                "succeeded": stats.succeeded,
                "failed": stats.failed,
                "total_prompt_tokens": stats.total_prompt_tokens,
                "total_completion_tokens": stats.total_completion_tokens,
                "total_elapsed_ms": round(stats.total_elapsed_ms, 1),
                "cache_session": stats.cache_session,
            },
            "results": [
                {
                    "path": r.path,
                    "summary": r.summary,
                    "usage": r.usage,
                    "error": r.error,
                }
                for r in stats.results
            ],
        }, ensure_ascii=False, indent=2))
    else:
        for r in stats.results:
            _print_result(r, fmt)

    _print_batch_stats(stats)
    if stats.cache_session and not stats.cache_session["prefix_stable"]:
        typer.echo(
            "\n[WARNING] Prefix was not stable across all requests. "
            "Cache hit rate may be reduced.",
            err=True,
        )


@app.command()
def benchmark(
    glob_pattern: str = typer.Argument(..., help="File glob pattern, e.g. 'src/**/*.py'"),
    model: Optional[str] = _opt_model,
    api_key: Optional[str] = _opt_api_key,
    base_url: Optional[str] = _opt_base_url,
    template_name: Optional[str] = _opt_template_name,
    templates_path: Optional[str] = _opt_templates_path,
    max_tokens: Optional[int] = _opt_max_tokens,
    temperature: Optional[float] = _opt_temperature,
    verbose: bool = _opt_verbose,
):
    """A/B test cache effectiveness.

    Runs the same files twice — with and without cache session —
    then compares token usage and cost.
    """
    if verbose:
        logging.basicConfig(level=logging.INFO)

    cfg = _build_config(
        api_key=api_key,
        base_url=base_url,
        model=model,
        max_tokens=max_tokens,
        temperature=temperature,
        concurrency=1,  # sequential for fair comparison
    )
    if template_name:
        cfg.template = template_name

    template = get_template(cfg.template, custom_path=templates_path)

    paths = sorted(glob.glob(glob_pattern, recursive=True))
    paths = [p for p in paths if Path(p).is_file()]
    if not paths:
        typer.echo(f"No files matched: {glob_pattern}", err=True)
        raise typer.Exit(1)

    # Sample if too many files
    sample_size = min(len(paths), 20)
    if len(paths) > sample_size:
        import random
        paths = random.sample(paths, sample_size)
        typer.echo(f"Sampled {sample_size} files for benchmark")

    result = run_benchmark(paths, config=cfg, template=template)
    typer.echo(format_benchmark(result))


@templates_app.command("list")
def template_list(
    templates_path: Optional[str] = _opt_templates_path,
):
    """List available prompt templates."""
    items = list_templates(custom_path=templates_path)
    for item in items:
        typer.echo(f"  {item['name']:20s}  {item['description']}")


@templates_app.command("show")
def template_show(
    name: str = typer.Argument(..., help="Template name"),
    templates_path: Optional[str] = _opt_templates_path,
):
    """Show a template's system and user prompts."""
    template = get_template(name, custom_path=templates_path)
    typer.echo(f"# {template.name}\n")
    typer.echo(f"## System\n\n{template.system}\n")
    typer.echo(f"## User\n\n{template.user}\n")


@app.command()
def hook(
    name: str = typer.Argument("post-commit", help="Hook name: post-commit"),
):
    """Install a git hook into the current repo.

    Copies the hook script from the contrib/ directory and makes it executable.
    Requires the glm-summarizer source to be checked out locally.
    """
    import shutil
    import stat
    from pathlib import Path

    # Find contrib directory
    contrib = Path(__file__).resolve().parent.parent.parent / "contrib"
    hook_src = contrib / name
    if not hook_src.exists():
        typer.echo(f"Hook '{name}' not found in {contrib}/", err=True)
        available = [p.name for p in contrib.iterdir() if p.is_file() and not p.suffix]
        if available:
            typer.echo(f"Available: {', '.join(available)}")
        raise typer.Exit(1)

    # Find git root
    try:
        import subprocess
        git_root = subprocess.check_output(
            ["git", "rev-parse", "--show-toplevel"],
            text=True,
        ).strip()
    except Exception:
        typer.echo("Not in a git repository", err=True)
        raise typer.Exit(1)

    hook_dst = Path(git_root) / ".git" / "hooks" / name
    shutil.copy(hook_src, hook_dst)
    hook_dst.chmod(hook_dst.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    typer.echo(f"Installed {name} hook → {hook_dst}")
    typer.echo(f"To uninstall: rm {hook_dst}")


@app.command()
def config(
    api_key: Optional[str] = _opt_api_key,
    base_url: Optional[str] = _opt_base_url,
    model: Optional[str] = _opt_model,
):
    """Show current configuration (with sensitive fields masked)."""
    cfg = Config.load(
        api_key=api_key,
        base_url=base_url,
        model=model,
    )
    typer.echo(f"  base_url:    {cfg.base_url}")
    typer.echo(f"  model:       {cfg.model}")
    typer.echo(f"  max_tokens:  {cfg.max_tokens}")
    typer.echo(f"  temperature: {cfg.temperature}")
    typer.echo(f"  concurrency: {cfg.concurrency}")
    typer.echo(f"  template:    {cfg.template}")
    # Mask API key
    if cfg.api_key:
        masked = cfg.api_key[:4] + "****" + cfg.api_key[-4:] if len(cfg.api_key) > 8 else "****"
        typer.echo(f"  api_key:     {masked}")
    else:
        typer.echo(f"  api_key:     (not set)")


def main():
    app()


if __name__ == "__main__":
    main()
