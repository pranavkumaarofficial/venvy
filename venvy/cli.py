"""
Command-line interface for venvy
Agent-friendly Python virtual environment manager with structured JSON output,
semantic exit codes, and non-interactive operation modes.
"""
import sys
import json
import os
from pathlib import Path
from typing import List, Optional
from datetime import datetime

import click
from rich.console import Console
from rich.table import Table
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.text import Text
from rich.prompt import Confirm

from venvy.discovery import EnvironmentDiscovery
from venvy.analysis import EnvironmentAnalysis
from venvy.cleanup import EnvironmentCleanup
from venvy.models import EnvironmentType, HealthStatus
from venvy.utils import human_readable_size, get_platform_info
from venvy.display import VenvyDisplay
from venvy.exit_codes import ExitCode
from venvy import __version__


# Global console for rich output - disable emoji on Windows for compatibility
console = Console(emoji=not sys.platform.startswith('win'))
display = VenvyDisplay(console)


def _output_result(data: dict, exit_code: int = 0):
    """Output structured JSON result for agent consumption.
    Uses click.echo for clean output (no Rich color codes)."""
    result = {"exit_code": exit_code, "success": exit_code == 0, **data}
    click.echo(json.dumps(result, indent=2, default=str))
    sys.exit(exit_code)


def _is_json_mode(ctx) -> bool:
    """Check if JSON output mode is active."""
    return ctx.obj.get('json_output', False) if ctx.obj else False


def _is_auto_yes(ctx) -> bool:
    """Check if auto-yes mode is active (--yes or --json)."""
    return ctx.obj.get('yes', False) if ctx.obj else False


def _is_quiet(ctx) -> bool:
    """Check if quiet mode is active."""
    return ctx.obj.get('quiet', False) if ctx.obj else False


def _auto_detect_env() -> Optional[Path]:
    """Auto-detect virtual environment: VIRTUAL_ENV env var -> .venv -> venv in cwd."""
    venv_env = os.environ.get('VIRTUAL_ENV')
    if venv_env:
        p = Path(venv_env)
        if p.exists():
            return p

    cwd = Path.cwd()
    for candidate in ['.venv', 'venv', 'env', '.env']:
        test_path = cwd / candidate
        if test_path.exists() and test_path.is_dir():
            return test_path
    return None


def _enable_json_flag(ctx, param, value):
    """Callback for the injected per-command --json: set JSON mode on the shared context.

    Lets `--json` be passed AFTER any subcommand (e.g. `venvy ls --json`), not only
    before it (`venvy --json ls`). This is the form users and agents naturally type,
    and the form venvy's own generated CLAUDE.md emits. `--json` implies --yes/--quiet,
    matching the group-level flag.
    """
    if value:
        ctx.ensure_object(dict)
        ctx.obj['json_output'] = True
        ctx.obj['yes'] = True
        ctx.obj['quiet'] = True
    return value


class VenvyGroup(click.Group):
    """Group that injects a `--json` flag into every subcommand that lacks its own.

    Keeps `--json` position-independent across the whole CLI with no per-command edits
    and no change to command signatures (the injected option uses expose_value=False).
    """

    def add_command(self, cmd, name=None):
        existing = {opt for param in cmd.params for opt in getattr(param, "opts", [])}
        if "--json" not in existing:
            cmd.params.append(click.Option(
                ["--json"], is_flag=True, expose_value=False, is_eager=True,
                callback=_enable_json_flag, help="Output as JSON (agent/CI friendly)",
            ))
        super().add_command(cmd, name)


@click.group(cls=VenvyGroup)
@click.version_option(version=__version__, prog_name="venvy")
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.option('--json', 'json_output', is_flag=True, help='Output as JSON (implies --yes)')
@click.option('--yes', '-y', is_flag=True, help='Skip all confirmation prompts')
@click.option('--quiet', '-q', is_flag=True, help='Suppress non-essential output')
@click.pass_context
def main(ctx, verbose, json_output, yes, quiet):
    """
    venvy - Agent-Safe Python Virtual Environment Manager

    Discover, analyze, create, and manage Python virtual environments.
    Use --json for structured output that AI agents can parse.
    """
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose
    ctx.obj['json_output'] = json_output
    ctx.obj['yes'] = yes or json_output  # --json implies --yes
    ctx.obj['quiet'] = quiet or json_output  # --json implies --quiet

    if verbose and not json_output:
        console.print(f"[dim]venvy v{__version__} on {get_platform_info()['system']}[/dim]")


# ============================================================================
# DISCOVERY & ANALYSIS COMMANDS (Slower - Filesystem Scanning)
# ============================================================================

@main.command()
@click.option('--path', '-p', type=click.Path(exists=True, path_type=Path),
              help='Search path for environments')
@click.option('--type', '-t', 'env_type',
              type=click.Choice(['venv', 'conda', 'pyenv', 'virtualenv'], case_sensitive=False),
              help='Filter by environment type')
@click.option('--format', '-f', 'output_format',
              type=click.Choice(['table', 'json', 'simple'], case_sensitive=False),
              default='table', help='Output format')
@click.option('--sort', '-s', 'sort_by',
              type=click.Choice(['name', 'size', 'age', 'usage'], case_sensitive=False),
              default='name', help='Sort environments by field')
@click.option('--fast', is_flag=True, default=True, help='Use fast scanning (default: enabled)')
@click.option('--thorough', is_flag=True, help='Disable fast scanning for complete results')
@click.pass_context
def list(ctx, path, env_type, output_format, sort_by, fast, thorough):
    """List all Python virtual environments"""
    json_mode = _is_json_mode(ctx)

    analysis = EnvironmentAnalysis()
    discovery = EnvironmentDiscovery()

    use_fast_scan = fast and not thorough
    search_paths = [path] if path else None

    if json_mode:
        environments = discovery.discover_all(search_paths, use_fast_scan=use_fast_scan)
        if environments:
            environments = analysis.analyze_all_environments(environments, use_parallel=use_fast_scan)
    else:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            discover_task = progress.add_task("Discovering environments...", total=None)
            environments = discovery.discover_all(search_paths, use_fast_scan=use_fast_scan)
            progress.update(discover_task, description="Discovery complete")

            if environments:
                analyze_task = progress.add_task("Analyzing environments...", total=len(environments))
                environments = analysis.analyze_all_environments(environments, use_parallel=use_fast_scan)
                progress.update(analyze_task, advance=len(environments))

    # Filter by type if specified
    if env_type:
        env_type_enum = EnvironmentType(env_type.lower())
        environments = [env for env in environments if env.type == env_type_enum]

    # Sort environments
    environments = _sort_environments(environments, sort_by)

    if json_mode or output_format == 'json':
        data = [env.to_dict() for env in environments]
        if json_mode:
            _output_result({"environments": data, "count": len(data)})
        else:
            _output_json(environments)
        return

    if not environments:
        console.print("No Python virtual environments found.")
        if path:
            console.print(f"   Searched in: {path}")
        console.print("   Try running without filters or check different locations.")
        return

    if output_format == 'simple':
        _output_simple(environments)
    else:
        display.show_environments_table(environments)


@main.command()
@click.option('--path', '-p', type=click.Path(exists=True, path_type=Path),
              help='Search path for environments')
@click.option('--top', '-n', type=int, default=10,
              help='Show top N largest environments')
@click.option('--format', '-f', 'output_format',
              type=click.Choice(['table', 'json'], case_sensitive=False),
              default='table', help='Output format')
@click.pass_context
def size(ctx, path, top, output_format):
    """Show environment sizes and disk usage"""
    json_mode = _is_json_mode(ctx)

    analysis = EnvironmentAnalysis()
    discovery = EnvironmentDiscovery()

    search_paths = [path] if path else None

    if json_mode:
        environments = discovery.discover_all(search_paths)
        environments = analysis.analyze_all_environments(environments)
    else:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Analyzing environment sizes...", total=None)
            environments = discovery.discover_all(search_paths)
            environments = analysis.analyze_all_environments(environments)
            progress.update(task, description="Analysis complete")

    if not environments:
        if json_mode:
            _output_result({"environments": [], "count": 0})
        console.print("No environments found to analyze.")
        return

    environments = sorted(environments, key=lambda e: e.size_bytes or 0, reverse=True)
    if top and len(environments) > top:
        environments = environments[:top]

    if json_mode or output_format == 'json':
        data = [env.to_dict() for env in environments]
        if json_mode:
            _output_result({"environments": data, "count": len(data)})
        else:
            _output_json(environments)
    else:
        display.show_size_analysis(environments)


@main.command()
@click.argument('environment', required=False)
@click.option('--path', '-p', type=click.Path(exists=True, path_type=Path),
              help='Search path for environments')
@click.pass_context
def info(ctx, environment, path):
    """Show detailed information about an environment"""
    json_mode = _is_json_mode(ctx)

    if not environment:
        if json_mode:
            _output_result({"error": "No environment specified"}, ExitCode.ENV_NOT_FOUND)
        console.print("Please specify an environment name or path")
        console.print("   Example: venvy info myenv")
        return

    discovery = EnvironmentDiscovery()
    analysis = EnvironmentAnalysis()

    env_info = discovery.find_environment(environment)

    if not env_info:
        if json_mode:
            _output_result({"error": f"Environment '{environment}' not found"}, ExitCode.ENV_NOT_FOUND)
        console.print(f"Environment '{environment}' not found")
        sys.exit(ExitCode.ENV_NOT_FOUND)

    if json_mode:
        analyzed_env = analysis.analyze_environment(env_info)
        _output_result({"environment": analyzed_env.to_dict()})
    else:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Analyzing environment...", total=None)
            analyzed_env = analysis.analyze_environment(env_info)
            progress.update(task, description="Analysis complete")
        display.show_environment_details(analyzed_env)


@main.command()
@click.option('--path', '-p', type=click.Path(exists=True, path_type=Path),
              help='Search path for environments')
@click.pass_context
def health(ctx, path):
    """Check health status of all environments"""
    json_mode = _is_json_mode(ctx)

    discovery = EnvironmentDiscovery()
    analysis = EnvironmentAnalysis()

    search_paths = [path] if path else None

    if json_mode:
        environments = discovery.discover_all(search_paths)
        environments = analysis.analyze_all_environments(environments)
    else:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Checking environment health...", total=None)
            environments = discovery.discover_all(search_paths)
            environments = analysis.analyze_all_environments(environments)
            progress.update(task, description="Health check complete")

    if not environments:
        if json_mode:
            _output_result({"environments": [], "count": 0})
        console.print("No environments found to check.")
        return

    if json_mode:
        data = [{"name": e.name, "path": str(e.path), "health": e.health_status.value,
                 "issues": e.health_issues or []} for e in environments]
        _output_result({"environments": data, "count": len(data)})
    else:
        display.show_health_report(environments)


@main.command()
@click.option('--path', '-p', type=click.Path(exists=True, path_type=Path),
              help='Search path for environments')
@click.option('--scan', is_flag=True, help='Use filesystem scan instead of registry')
@click.option('--max-suggestions', '-n', type=int, default=10,
              help='Maximum number of suggestions to show')
@click.option('--min-confidence', type=float, default=0.5,
              help='Minimum confidence threshold (0.0 - 1.0)')
@click.pass_context
def suggest(ctx, path, scan, max_suggestions, min_confidence):
    """Get intelligent cleanup suggestions"""
    json_mode = _is_json_mode(ctx)

    discovery = EnvironmentDiscovery()
    analysis = EnvironmentAnalysis()

    suggestions = []
    environments = []

    if json_mode:
        if scan or path:
            search_paths = [path] if path else None
            environments = discovery.discover_all(search_paths)
            environments = analysis.analyze_all_environments(environments)
            suggestions = analysis.generate_cleanup_suggestions(environments)
        else:
            from venvy.registry import VenvRegistry
            from venvy.models import EnvironmentInfo

            registry = VenvRegistry()
            records = registry.list_all()

            for record in records:
                size_bytes = int(record.size_mb * 1024 * 1024) if record.size_mb else None
                days_since_used = None
                if record.last_used_at:
                    try:
                        dt = datetime.fromisoformat(record.last_used_at.replace("T", " "))
                        days_since_used = (datetime.now() - dt).days
                    except Exception:
                        pass

                env = EnvironmentInfo(
                    name=record.name, path=Path(record.path),
                    type=EnvironmentType.UNKNOWN, python_version=record.python_version,
                    size_bytes=size_bytes, package_count=record.package_count,
                    health_status=HealthStatus.UNKNOWN, activation_count=record.activation_count,
                    days_since_used=days_since_used,
                    linked_projects=[Path(record.project_path)] if record.project_path else None,
                    is_orphaned=record.project_path is None
                )
                environments.append(env)

            suggestions = analysis.generate_cleanup_suggestions(environments)
    else:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Generating suggestions...", total=None)

            if scan or path:
                search_paths = [path] if path else None
                environments = discovery.discover_all(search_paths)
                environments = analysis.analyze_all_environments(environments)
                suggestions = analysis.generate_cleanup_suggestions(environments)
            else:
                from venvy.registry import VenvRegistry
                from venvy.models import EnvironmentInfo

                registry = VenvRegistry()
                records = registry.list_all()

                for record in records:
                    size_bytes = int(record.size_mb * 1024 * 1024) if record.size_mb else None
                    days_since_used = None
                    if record.last_used_at:
                        try:
                            dt = datetime.fromisoformat(record.last_used_at.replace("T", " "))
                            days_since_used = (datetime.now() - dt).days
                        except Exception:
                            pass

                    env = EnvironmentInfo(
                        name=record.name, path=Path(record.path),
                        type=EnvironmentType.UNKNOWN, python_version=record.python_version,
                        size_bytes=size_bytes, package_count=record.package_count,
                        health_status=HealthStatus.UNKNOWN, activation_count=record.activation_count,
                        days_since_used=days_since_used,
                        linked_projects=[Path(record.project_path)] if record.project_path else None,
                        is_orphaned=record.project_path is None
                    )
                    environments.append(env)

                suggestions = analysis.generate_cleanup_suggestions(environments)

            progress.update(task, description="Analysis complete")

    # Filter by confidence
    suggestions = [s for s in suggestions if s.confidence >= min_confidence]
    if max_suggestions and len(suggestions) > max_suggestions:
        suggestions = suggestions[:max_suggestions]

    if json_mode:
        data = [{"name": s.environment.name, "path": str(s.environment.path),
                 "reason": s.reason, "confidence": s.confidence,
                 "space_recovered": s.space_recovered, "risk_level": s.risk_level}
                for s in suggestions]
        _output_result({"suggestions": data, "count": len(data)})

    if not suggestions:
        if scan or path:
            console.print("No cleanup suggestions needed! Your environments look good.")
        else:
            console.print("[yellow]No suggestions from registry data.[/yellow]")
            console.print("[dim]Try 'venvy suggest --scan' or 'venvy suggest --path <dir>' for deeper analysis.[/dim]")
        return

    display.show_cleanup_suggestions(suggestions)


@main.command('scan-stats')
@click.option('--path', '-p', type=click.Path(exists=True, path_type=Path),
              help='Search path for environments')
@click.pass_context
def scan_stats(ctx, path):
    """Show system-wide environment statistics"""
    json_mode = _is_json_mode(ctx)

    discovery = EnvironmentDiscovery()
    analysis = EnvironmentAnalysis()

    search_paths = [path] if path else None

    if json_mode:
        environments = discovery.discover_all(search_paths)
        environments = analysis.analyze_all_environments(environments)
        summary = analysis.get_system_summary(environments)
        _output_result({
            "total_environments": summary.total_environments,
            "total_size_bytes": summary.total_size_bytes,
            "total_size_human": summary.total_size_human,
            "environment_types": summary.environment_types,
            "health_distribution": summary.health_distribution,
            "potential_savings_bytes": summary.potential_savings_bytes,
        })
    else:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Gathering statistics...", total=None)
            environments = discovery.discover_all(search_paths)
            environments = analysis.analyze_all_environments(environments)
            summary = analysis.get_system_summary(environments)
            progress.update(task, description="Statistics complete")
        display.show_system_summary(summary, environments)


@main.command()
@click.option('--path', '-p', type=click.Path(exists=True, path_type=Path),
              help='Search path for environments')
@click.pass_context
def duplicates(ctx, path):
    """Find environments with similar package lists"""
    json_mode = _is_json_mode(ctx)

    discovery = EnvironmentDiscovery()
    analysis = EnvironmentAnalysis()

    search_paths = [path] if path else None

    if json_mode:
        environments = discovery.discover_all(search_paths)
        environments = analysis.analyze_all_environments(environments)
        duplicate_groups = analysis.find_duplicate_environments(environments)
        groups_data = []
        for group in duplicate_groups:
            groups_data.append([{"name": e.name, "path": str(e.path)} for e in group])
        _output_result({"duplicate_groups": groups_data, "count": len(groups_data)})
    else:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Finding duplicate environments...", total=None)
            environments = discovery.discover_all(search_paths)
            environments = analysis.analyze_all_environments(environments)
            duplicate_groups = analysis.find_duplicate_environments(environments)
            progress.update(task, description="Analysis complete")

        if not duplicate_groups:
            console.print("No duplicate environments found!")
            return

        display.show_duplicate_environments(duplicate_groups)


@main.command()
@click.argument('environment')
@click.option('--force', '-f', is_flag=True, help='Skip confirmation prompt')
@click.pass_context
def remove(ctx, environment, force):
    """Remove a specific environment"""
    json_mode = _is_json_mode(ctx)
    auto_yes = _is_auto_yes(ctx)

    discovery = EnvironmentDiscovery()

    env_info = discovery.find_environment(environment)

    if not env_info:
        if json_mode:
            _output_result({"error": f"Environment '{environment}' not found"}, ExitCode.ENV_NOT_FOUND)
        console.print(f"Environment '{environment}' not found")
        sys.exit(ExitCode.ENV_NOT_FOUND)

    if not json_mode:
        console.print(f"Found environment: [bold]{env_info.name}[/bold]")
        console.print(f"   Path: {env_info.path}")
        if env_info.size_bytes:
            console.print(f"   Size: {human_readable_size(env_info.size_bytes)}")

    # Confirm removal
    if not force and not auto_yes:
        if not Confirm.ask(f"Are you sure you want to remove '{env_info.name}'?"):
            console.print("Removal cancelled")
            return

    cleanup = EnvironmentCleanup()
    success = cleanup.remove_environment(env_info, create_backup=True)

    if success:
        if json_mode:
            _output_result({"removed": env_info.name, "path": str(env_info.path),
                            "size_freed": env_info.size_bytes or 0})
        else:
            console.print(f"Successfully removed '{env_info.name}'")
            if env_info.size_bytes:
                console.print(f"   Freed {human_readable_size(env_info.size_bytes)} of disk space")
    else:
        if json_mode:
            _output_result({"error": "Failed to remove environment"}, ExitCode.PERMISSION_DENIED)
        console.print("Failed to remove environment")
        sys.exit(ExitCode.PERMISSION_DENIED)


@main.command()
@click.option('--unused-days', '-d', type=int, default=90,
              help='Remove environments unused for N days')
@click.option('--dry-run', is_flag=True, help='Show what would be removed without actually removing')
@click.option('--force', '-f', is_flag=True, help='Skip confirmation prompts')
@click.option('--path', '-p', type=click.Path(exists=True, path_type=Path),
              help='Search path for environments')
@click.pass_context
def clean(ctx, unused_days, dry_run, force, path):
    """Clean up unused environments"""
    json_mode = _is_json_mode(ctx)
    auto_yes = _is_auto_yes(ctx)

    discovery = EnvironmentDiscovery()
    analysis = EnvironmentAnalysis()

    search_paths = [path] if path else None

    if json_mode:
        environments = discovery.discover_all(search_paths)
        environments = analysis.analyze_all_environments(environments)
    else:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            console=console
        ) as progress:
            task = progress.add_task("Finding environments to clean...", total=None)
            environments = discovery.discover_all(search_paths)
            environments = analysis.analyze_all_environments(environments)
            progress.update(task, description="Analysis complete")

    to_remove = []
    for env in environments:
        if (env.days_since_used is not None and
            env.days_since_used >= unused_days and
            env.health_status != HealthStatus.HEALTHY):
            to_remove.append(env)

    if not to_remove:
        if json_mode:
            _output_result({"removed": [], "count": 0, "space_freed": 0})
        else:
            console.print(f"No environments found that are unused for {unused_days}+ days")
        return

    total_size = sum(env.size_bytes or 0 for env in to_remove)

    if dry_run:
        if json_mode:
            data = [{"name": e.name, "path": str(e.path), "size_bytes": e.size_bytes or 0,
                     "days_unused": e.days_since_used} for e in to_remove]
            _output_result({"dry_run": True, "would_remove": data, "count": len(data),
                            "space_would_free": total_size})
        else:
            console.print(f"\nFound {len(to_remove)} environment(s) to clean:")
            for env in to_remove:
                console.print(f"   {env.name} ({human_readable_size(env.size_bytes or 0)}) - {env.days_since_used} days unused")
            console.print(f"\nTotal space to recover: [bold]{human_readable_size(total_size)}[/bold]")
            console.print("\n[dim]Dry run complete - no environments were actually removed[/dim]")
        return

    if not json_mode:
        console.print(f"\nFound {len(to_remove)} environment(s) to clean:")
        for env in to_remove:
            console.print(f"   {env.name} ({human_readable_size(env.size_bytes or 0)}) - {env.days_since_used} days unused")
        console.print(f"\nTotal space to recover: [bold]{human_readable_size(total_size)}[/bold]")

    if not force and not auto_yes:
        if not Confirm.ask(f"Remove {len(to_remove)} environment(s)?"):
            console.print("Cleanup cancelled")
            return

    cleanup = EnvironmentCleanup()
    results = cleanup.batch_remove_environments(to_remove, create_backups=True)

    removed_count = len(results['success'])
    failed_count = len(results['failed'])
    removed_size = sum(env.size_bytes or 0 for env in results['success'])

    if json_mode:
        _output_result({
            "removed": [{"name": e.name, "path": str(e.path)} for e in results['success']],
            "failed": [{"name": e.name, "path": str(e.path)} for e in results['failed']],
            "count": removed_count,
            "space_freed": removed_size,
        })
    else:
        for env in results['success']:
            console.print(f"Removed {env.name}")
        for env in results['failed']:
            console.print(f"[red]Failed to remove {env.name}[/red]")
        console.print(f"\nCleanup complete! Removed: {removed_count}, Space freed: {human_readable_size(removed_size)}")


@main.command()
@click.option('--clear', is_flag=True, help='Clear all cached data')
@click.option('--stats', 'show_stats', is_flag=True, help='Show cache statistics')
@click.pass_context
def cache(ctx, clear, show_stats):
    """Manage venvy cache for better performance"""
    json_mode = _is_json_mode(ctx)
    from venvy.performance import EnvironmentCache

    cache_manager = EnvironmentCache()

    if clear:
        cache_manager.clear_cache()
        if json_mode:
            _output_result({"action": "cleared"})
        else:
            console.print("Cache cleared successfully")
        return

    if show_stats:
        cache_dir = cache_manager.cache_dir
        if cache_dir.exists():
            cache_files = list(cache_dir.glob("*.json"))
            total_size = sum(f.stat().st_size for f in cache_files if f.exists())

            if json_mode:
                _output_result({
                    "cache_dir": str(cache_dir),
                    "file_count": len(cache_files),
                    "total_size_bytes": total_size,
                })
            else:
                console.print(f"Cache directory: {cache_dir}")
                console.print(f"Cache files: {len(cache_files)}")
                console.print(f"Total size: {human_readable_size(total_size)}")

                env_cache = cache_manager.cache_file
                if env_cache.exists():
                    try:
                        with open(env_cache) as f:
                            data = json.load(f)
                        cached_at = data.get('cached_at', '')
                        env_count = len(data.get('environments', []))
                        console.print(f"Environment cache: {env_count} environments")
                        console.print(f"Last updated: {cached_at}")
                    except Exception:
                        console.print("Environment cache: corrupted")
        else:
            if json_mode:
                _output_result({"cache_dir": str(cache_dir), "file_count": 0, "total_size_bytes": 0})
            else:
                console.print("No cache data found")
        return

    if json_mode:
        _output_result({"hint": "Use --clear or --stats"})
    else:
        console.print("Venvy uses intelligent caching to improve performance")
        console.print("Use --clear to clear cache or --stats to show cache information")


def _sort_environments(environments: List, sort_by: str):
    """Sort environments by specified field"""
    if sort_by == 'size':
        return sorted(environments, key=lambda e: e.size_bytes or 0, reverse=True)
    elif sort_by == 'age':
        return sorted(environments, key=lambda e: e.created_date or datetime.min, reverse=True)
    elif sort_by == 'usage':
        return sorted(environments, key=lambda e: e.activation_count or 0, reverse=True)
    else:  # name
        return sorted(environments, key=lambda e: e.name.lower())


def _output_json(environments: List):
    """Output environments as JSON"""
    data = [env.to_dict() for env in environments]
    console.print_json(json.dumps(data, indent=2))


def _output_simple(environments: List):
    """Output environments in simple format"""
    for env in environments:
        console.print(f"{env.name} ({env.path})")


# ============================================================================
# REGISTRY-BASED COMMANDS (Fast - No Scanning!)
# ============================================================================

@main.command()
@click.argument('venv_path', type=click.Path(exists=True, path_type=Path), required=False)
@click.option('--project', '-p', type=click.Path(exists=True, path_type=Path),
              help='Project directory using this venv')
@click.option('--name', '-n', help='Custom name for this venv')
@click.pass_context
def register(ctx, venv_path, project, name):
    """Register a virtual environment for tracking

    Once registered, venvs appear in venvy ls without slow scanning.

    Examples:
        venvy register .venv
        venvy register /path/to/venv --project /path/to/project
        venvy register .venv --name myproject
    """
    json_mode = _is_json_mode(ctx)
    from venvy.registry import VenvRegistry

    # Default to current directory's .venv or venv
    if venv_path is None:
        cwd = Path.cwd()
        for candidate in ['.venv', 'venv', 'env', '.env']:
            test_path = cwd / candidate
            if test_path.exists() and test_path.is_dir():
                venv_path = test_path
                break

        if venv_path is None:
            if json_mode:
                _output_result({"error": "No venv found in current directory"}, ExitCode.ENV_NOT_FOUND)
            console.print("[red]Error: No venv found in current directory[/red]")
            console.print("Usage: venvy register <path-to-venv>")
            sys.exit(ExitCode.ENV_NOT_FOUND)

    if project is None:
        project = venv_path.parent

    registry = VenvRegistry()

    if not json_mode:
        console.print(f"Registering venv: {venv_path}")

    if registry.register(venv_path, project, name):
        if json_mode:
            _output_result({"registered": True, "path": str(venv_path), "project": str(project)})
        else:
            console.print("[green]Venv registered successfully![/green]")
            console.print(f"  Path: {venv_path}")
            console.print(f"  Project: {project}")
            console.print(f"\nNow it will appear in 'venvy ls' instantly (no scanning needed)")
    else:
        if json_mode:
            _output_result({"error": "Failed to register venv"}, ExitCode.GENERAL_ERROR)
        console.print("[red]Failed to register venv[/red]")
        sys.exit(ExitCode.GENERAL_ERROR)


@main.command()
@click.argument('name_or_path', required=False)
@click.pass_context
def track(ctx, name_or_path):
    """Update last-used timestamp for a venv (called automatically on activation)"""
    from venvy.registry import VenvRegistry

    if name_or_path is None:
        name_or_path = os.environ.get('VIRTUAL_ENV')

    if not name_or_path:
        if _is_json_mode(ctx):
            _output_result({"error": "No venv specified or active"}, ExitCode.ENV_NOT_FOUND)
        console.print("[yellow]No venv specified or active[/yellow]")
        return

    registry = VenvRegistry()
    registry.track_activation(Path(name_or_path), project_path=Path.cwd())

    if _is_json_mode(ctx):
        _output_result({"tracked": name_or_path})


@main.command('ls')
@click.option('--sort', '-s', type=click.Choice(['name', 'recent', 'size', 'project']),
              default='recent', help='Sort by field')
@click.option('--format', '-f', type=click.Choice(['table', 'json', 'simple']),
              default='table', help='Output format')
@click.option('--hide-missing', is_flag=True, help='Hide entries whose paths are missing')
@click.pass_context
def ls_command(ctx, sort, format, hide_missing):
    """List all registered venvs (INSTANT - no scanning!)

    This is FAST because it reads from the registry database
    instead of scanning the filesystem.

    First time? Run 'venvy scan' to find and register your existing venvs.
    """
    json_mode = _is_json_mode(ctx)
    from venvy.registry import VenvRegistry

    registry = VenvRegistry()
    if sort == 'recent':
        sort_key = 'last_used_at'
    elif sort == 'project':
        sort_key = 'project_path'
    elif sort == 'size':
        sort_key = 'size_mb'
    else:
        sort_key = sort
    venvs = registry.list_all(sort_by=sort_key)

    filtered = []
    for v in venvs:
        exists = Path(v.path).exists()
        is_missing = not exists
        if v.missing != is_missing:
            registry.mark_missing(Path(v.path), is_missing)
            v.missing = is_missing
        if hide_missing and is_missing:
            continue
        filtered.append(v)

    venvs = filtered

    if json_mode or format == 'json':
        data = [v.to_dict() for v in venvs]
        if json_mode:
            stats_data = registry.get_stats()
            _output_result({"venvs": data, "count": len(data), "stats": stats_data})
        else:
            console.print_json(json.dumps(data, indent=2))
        return

    if not venvs:
        console.print("[yellow]No registered venvs found[/yellow]")
        console.print("\nTo register venvs:")
        console.print("  1. Run 'venvy scan' to find existing venvs")
        console.print("  2. Or manually: 'venvy register /path/to/venv'")
        console.print("  3. Or auto-track: 'venvy shell-hook' to install shell integration")
        return

    if format == 'simple':
        for v in venvs:
            suffix = " [missing]" if v.missing else ""
            console.print(f"{v.name} -> {v.path}{suffix}")
    else:
        # Table format
        table = Table(title=f"Registered Virtual Environments ({len(venvs)} total)")
        table.add_column("Name", style="cyan")
        table.add_column("Status", style="yellow")
        table.add_column("Python", style="green")
        table.add_column("Packages", justify="right")
        table.add_column("Size", justify="right")
        table.add_column("Last Used", style="dim")
        table.add_column("Project", style="blue", no_wrap=False)

        for v in venvs:
            last_used = "never"
            if v.last_used_at:
                try:
                    dt = datetime.fromisoformat(v.last_used_at)
                    delta = datetime.now() - dt
                    if delta.days == 0:
                        last_used = "today"
                    elif delta.days == 1:
                        last_used = "yesterday"
                    elif delta.days < 7:
                        last_used = f"{delta.days}d ago"
                    elif delta.days < 30:
                        last_used = f"{delta.days//7}w ago"
                    else:
                        last_used = f"{delta.days//30}mo ago"
                except Exception:
                    pass

            table.add_row(
                v.name,
                "missing" if v.missing else "",
                v.python_version or "?",
                str(v.package_count) if v.package_count else "?",
                f"{v.size_mb:.1f}MB" if v.size_mb else "?",
                last_used,
                v.project_path or "?"
            )

        console.print(table)

        stats_data = registry.get_stats()
        console.print(f"\n[dim]Total: {stats_data['total_venvs']} venvs, {stats_data['total_size_mb']:.1f}MB, {stats_data['total_packages']} packages[/dim]")
        if stats_data.get('missing_venvs', 0) > 0:
            console.print(f"[yellow]{stats_data['missing_venvs']} venvs missing on disk (run 'venvy cleanup-registry')[/yellow]")
        if stats_data['unused_90_days'] > 0:
            console.print(f"[yellow]{stats_data['unused_90_days']} venvs unused for 90+ days[/yellow]")


@main.command()
@click.option('--home', is_flag=True, help='Scan home directory')
@click.option('--path', '-p', type=click.Path(exists=True, path_type=Path),
              help='Specific path to scan')
@click.option('--depth', '-d', type=int, default=3, help='Max depth to scan')
@click.pass_context
def scan(ctx, home, path, depth):
    """Scan filesystem for venvs and register them

    This is the SLOW operation - only run when needed.
    After scanning, use 'venvy ls' for instant results.

    Examples:
        venvy scan                  # Scan current directory
        venvy scan --home           # Scan home directory (slow!)
        venvy scan --path ~/projects
    """
    json_mode = _is_json_mode(ctx)
    from venvy.registry import VenvRegistry

    registry = VenvRegistry()

    if path:
        search_paths = [path]
    elif home:
        search_paths = [Path.home()]
    else:
        search_paths = [Path.cwd()]

    if not json_mode:
        console.print(f"Scanning {search_paths[0]} (depth={depth})...")
        console.print("[yellow]This may take a while...[/yellow]")

    if json_mode:
        registered = registry.scan_and_register_all(search_paths, max_depth=depth)
        _output_result({"registered": registered, "search_path": str(search_paths[0])})
    else:
        with Progress(console=console) as progress:
            task = progress.add_task("Scanning...", total=None)
            registered = registry.scan_and_register_all(search_paths, max_depth=depth)
            progress.update(task, completed=1)
        console.print(f"\n[green]Found and registered {registered} venv(s)[/green]")
        console.print("\nNow run 'venvy ls' to see them instantly!")


@main.command()
@click.pass_context
def current(ctx):
    """Show currently active venv"""
    json_mode = _is_json_mode(ctx)

    venv = os.environ.get('VIRTUAL_ENV')

    if venv:
        from venvy.registry import VenvRegistry
        registry = VenvRegistry()
        record = registry.get(venv)

        if json_mode:
            data = {"active": True, "path": venv}
            if record:
                data.update({"name": record.name, "python_version": record.python_version,
                             "project": record.project_path, "registered": True})
            else:
                data["registered"] = False
            _output_result(data)
        else:
            console.print(f"[green]Active venv:[/green] {venv}")
            if record:
                console.print(f"  Name: {record.name}")
                console.print(f"  Python: {record.python_version}")
                console.print(f"  Project: {record.project_path}")
            else:
                console.print("[dim]  (not registered - run 'venvy register' to track it)[/dim]")
    else:
        if json_mode:
            _output_result({"active": False}, ExitCode.ENV_NOT_FOUND)
        else:
            console.print("[yellow]No venv currently active[/yellow]")
            console.print("\nTo activate a venv:")
            console.print("  source /path/to/venv/bin/activate")


@main.command()
@click.option('--days', '-d', type=int, default=90, help='Consider unused after N days')
@click.option('--dry-run', is_flag=True, help='Show what would be cleaned')
@click.option('--force', '-f', is_flag=True, help='Skip confirmation prompt')
@click.pass_context
def cleanup(ctx, days, dry_run, force):
    """Remove venvs not used in N days

    Default: removes venvs unused for 90+ days
    """
    json_mode = _is_json_mode(ctx)
    auto_yes = _is_auto_yes(ctx)
    from venvy.registry import VenvRegistry

    registry = VenvRegistry()
    venvs = registry.list_all()

    to_remove = []
    for v in venvs:
        if v.last_used_at:
            try:
                dt = datetime.fromisoformat(v.last_used_at)
                age_days = (datetime.now() - dt).days
                if age_days >= days:
                    to_remove.append((v, age_days))
            except Exception:
                pass

    if not to_remove:
        if json_mode:
            _output_result({"removed": [], "count": 0, "space_freed_mb": 0})
        else:
            console.print(f"[green]No venvs unused for {days}+ days[/green]")
        return

    total_size = sum(v.size_mb or 0 for v, _ in to_remove)

    if dry_run:
        if json_mode:
            data = [{"name": v.name, "path": v.path, "age_days": age, "size_mb": v.size_mb or 0}
                    for v, age in to_remove]
            _output_result({"dry_run": True, "would_remove": data, "count": len(data),
                            "space_would_free_mb": total_size})
        else:
            console.print(f"[yellow]Found {len(to_remove)} venv(s) unused for {days}+ days:[/yellow]\n")
            for v, age in to_remove:
                console.print(f"  {v.name} - last used {age} days ago ({v.size_mb:.1f}MB)" if v.size_mb else f"  {v.name} - last used {age} days ago")
            console.print(f"\n[bold]Total space: {total_size:.1f}MB[/bold]")
            console.print("\n[dim]Dry run - no venvs removed[/dim]")
        return

    if not json_mode:
        console.print(f"[yellow]Found {len(to_remove)} venv(s) unused for {days}+ days:[/yellow]\n")
        for v, age in to_remove:
            console.print(f"  {v.name} - last used {age} days ago ({v.size_mb:.1f}MB)" if v.size_mb else f"  {v.name} - last used {age} days ago")
        console.print(f"\n[bold]Total space: {total_size:.1f}MB[/bold]")

    if not force and not auto_yes:
        if not Confirm.ask(f"\nRemove {len(to_remove)} venv(s)?"):
            console.print("Cancelled")
            return

    import shutil
    removed = 0
    removed_list = []
    failed_list = []
    for v, _ in to_remove:
        try:
            shutil.rmtree(v.path)
            registry.unregister(Path(v.path))
            removed += 1
            removed_list.append({"name": v.name, "path": v.path})
            if not json_mode:
                console.print(f"  [green]+[/green] Removed {v.name}")
        except Exception as e:
            failed_list.append({"name": v.name, "error": str(e)})
            if not json_mode:
                console.print(f"  [red]x[/red] Failed to remove {v.name}: {e}")

    if json_mode:
        _output_result({"removed": removed_list, "failed": failed_list,
                        "count": removed, "space_freed_mb": total_size})
    else:
        console.print(f"\n[green]Removed {removed}/{len(to_remove)} venvs ({total_size:.1f}MB freed)[/green]")


@main.command()
@click.option('--all', 'refresh_all', is_flag=True, help='Refresh all registered venvs')
@click.option('--path', '-p', type=click.Path(exists=True, path_type=Path),
              help='Refresh a specific venv path')
@click.option('--name', '-n', help='Refresh a venv by registered name')
@click.option('--max', 'max_count', type=int, default=0, help='Limit number of venvs to refresh')
@click.option('--stale-days', type=int, default=7, help='Refresh only if cache is older than N days')
@click.option('--force', is_flag=True, help='Refresh even if cache is recent')
@click.pass_context
def refresh(ctx, refresh_all, path, name, max_count, stale_days, force):
    """Refresh cached size/package metadata for registered venvs"""
    json_mode = _is_json_mode(ctx)
    from venvy.registry import VenvRegistry

    registry = VenvRegistry()

    targets = []
    if path:
        targets = [registry.get(str(Path(path).resolve()))]
    elif name:
        targets = [registry.get(name)]
    elif refresh_all:
        targets = registry.list_all()
    else:
        if json_mode:
            _output_result({"error": "Specify --all, --path, or --name"}, ExitCode.GENERAL_ERROR)
        console.print("[yellow]Specify --all, --path, or --name[/yellow]")
        return

    targets = [t for t in targets if t is not None]
    if not targets:
        if json_mode:
            _output_result({"refreshed": 0, "skipped": 0, "missing": 0})
        else:
            console.print("[yellow]No matching venvs found[/yellow]")
        return

    if max_count and len(targets) > max_count:
        targets = targets[:max_count]

    def _is_stale(ts: Optional[str], days_threshold: int) -> bool:
        if not ts:
            return True
        try:
            cached_at = datetime.fromisoformat(ts)
        except ValueError:
            return True
        return (datetime.now() - cached_at).days >= days_threshold

    refreshed = 0
    skipped = 0
    missing = 0

    for v in targets:
        if not force:
            size_stale = _is_stale(v.size_mb_cached_at, stale_days)
            pkg_stale = _is_stale(v.packages_cached_at, stale_days)
            if not (size_stale or pkg_stale):
                skipped += 1
                continue

        ok = registry.refresh_metadata(Path(v.path))
        if ok:
            refreshed += 1
        else:
            missing += 1

    if json_mode:
        _output_result({"refreshed": refreshed, "skipped": skipped, "missing": missing})
    else:
        console.print(f"[green]Refreshed: {refreshed}[/green]")
        if skipped:
            console.print(f"[dim]Skipped (fresh): {skipped}[/dim]")
        if missing:
            console.print(f"[yellow]Missing on disk: {missing}[/yellow]")


@main.command()
@click.pass_context
def doctor(ctx):
    """Diagnose common setup and registry issues"""
    json_mode = _is_json_mode(ctx)
    from venvy.registry import VenvRegistry

    checks = []

    registry = VenvRegistry()

    # Registry DB availability
    try:
        db_path = registry.db_path
        if db_path.exists():
            checks.append({"check": "registry_db", "status": "ok", "detail": str(db_path)})
            if not json_mode:
                console.print(f"[green]OK[/green] Registry DB: {db_path}")
        else:
            checks.append({"check": "registry_db", "status": "missing", "detail": str(db_path)})
            if not json_mode:
                console.print(f"[red]MISSING[/red] Registry DB not found at {db_path}")
    except Exception as e:
        checks.append({"check": "registry_db", "status": "error", "detail": str(e)})
        if not json_mode:
            console.print(f"[red]ERROR[/red] Registry DB check failed: {e}")

    # Stats / missing entries
    try:
        stats_data = registry.get_stats()
        checks.append({"check": "registry_entries", "status": "ok", "detail": stats_data['total_venvs']})
        if not json_mode:
            console.print(f"[green]OK[/green] Registry entries: {stats_data['total_venvs']}")

        if stats_data.get('missing_venvs', 0) > 0:
            checks.append({"check": "missing_venvs", "status": "warn",
                           "detail": stats_data['missing_venvs']})
            if not json_mode:
                console.print(f"[yellow]WARN[/yellow] Missing on disk: {stats_data['missing_venvs']} (run 'venvy cleanup-registry')")
        else:
            checks.append({"check": "missing_venvs", "status": "ok", "detail": 0})
            if not json_mode:
                console.print("[green]OK[/green] No missing entries detected")
    except Exception as e:
        checks.append({"check": "registry_entries", "status": "error", "detail": str(e)})
        if not json_mode:
            console.print(f"[red]ERROR[/red] Registry stats failed: {e}")

    # Shell hook presence
    try:
        from venvy.shell_integration import get_shell_config_path
        config_path = get_shell_config_path()

        if not config_path:
            home = Path.home()
            candidates = [
                home / "Documents" / "PowerShell" / "Microsoft.PowerShell_profile.ps1",
                home / "Documents" / "WindowsPowerShell" / "Microsoft.PowerShell_profile.ps1",
            ]
            for candidate in candidates:
                if candidate.exists():
                    config_path = candidate
                    break

        if config_path and config_path.exists():
            try:
                content = config_path.read_text(encoding="utf-8", errors="ignore")
                if "venvy shell-hook" in content or "venvy_track_activation" in content or "Venvy-Track-Activation" in content:
                    checks.append({"check": "shell_hook", "status": "ok", "detail": str(config_path)})
                    if not json_mode:
                        console.print(f"[green]OK[/green] Shell hook detected in {config_path}")
                else:
                    checks.append({"check": "shell_hook", "status": "warn", "detail": "Not detected"})
                    if not json_mode:
                        console.print(f"[yellow]WARN[/yellow] Shell hook not detected in {config_path}")
                        console.print("[dim]Install with: venvy shell-hook >> $PROFILE[/dim]")
            except Exception:
                checks.append({"check": "shell_hook", "status": "warn", "detail": "Could not read config"})
                if not json_mode:
                    console.print(f"[yellow]WARN[/yellow] Could not read shell config: {config_path}")
        else:
            shell = os.environ.get("SHELL") or "unknown"
            checks.append({"check": "shell_hook", "status": "warn", "detail": f"Config not found (SHELL={shell})"})
            if not json_mode:
                console.print(f"[yellow]WARN[/yellow] Shell config not found (SHELL={shell})")
                console.print("[dim]PowerShell users can run: venvy shell-hook --shell powershell >> $PROFILE[/dim]")
    except Exception as e:
        checks.append({"check": "shell_hook", "status": "warn", "detail": str(e)})
        if not json_mode:
            console.print(f"[yellow]WARN[/yellow] Shell hook check failed: {e}")

    if json_mode:
        all_ok = all(c["status"] in ("ok", "info") for c in checks)
        _output_result({"checks": checks, "healthy": all_ok})
    elif not json_mode:
        console.print("")  # blank line at end


@main.command('cleanup-registry')
@click.pass_context
def cleanup_registry(ctx):
    """Remove registry entries that point to missing venv paths"""
    json_mode = _is_json_mode(ctx)
    from venvy.registry import VenvRegistry

    registry = VenvRegistry()
    removed = registry.cleanup_missing()

    if json_mode:
        _output_result({"removed": removed})
    elif removed == 0:
        console.print("[green]Registry is clean. No missing entries found.[/green]")
    else:
        console.print(f"[yellow]Removed {removed} missing registry entries.[/yellow]")


@main.command('shell-hook')
@click.option('--shell', type=click.Choice(['bash', 'zsh', 'fish', 'powershell']),
              help='Shell type (auto-detected if not specified)')
def shell_hook(shell):
    """Generate shell hook for automatic venv tracking

    This allows venvy to automatically track when you activate venvs.

    Usage:
        venvy shell-hook >> ~/.bashrc
        venvy shell-hook --shell zsh >> ~/.zshrc
        venvy shell-hook --shell fish >> ~/.config/fish/config.fish
    """
    from venvy.shell_integration import install_shell_hook, get_shell_config_path

    if shell is None:
        shell_name = os.environ.get('SHELL', '').split('/')[-1]
        if 'bash' in shell_name:
            shell = 'bash'
        elif 'zsh' in shell_name:
            shell = 'zsh'
        elif 'fish' in shell_name:
            shell = 'fish'
        elif sys.platform.startswith('win'):
            shell = 'powershell'
        else:
            shell = 'bash'

    hook_content = install_shell_hook(shell)
    console.print(hook_content)

    console.print(f"\n[dim]# To install, run:[/dim]", style="dim")

    config_path = get_shell_config_path()
    if config_path:
        console.print(f"[dim]venvy shell-hook >> {config_path}[/dim]")
    else:
        console.print(f"[dim]venvy shell-hook >> ~/.{shell}rc[/dim]")


@main.command()
@click.option('--port', type=int, default=5173, help='Port for the UI server')
def ui(port):
    """Start the local venvy UI"""
    import subprocess as sp

    ui_script = Path(__file__).resolve().parents[1] / "ui" / "serve.py"
    if not ui_script.exists():
        console.print("[red]UI server not found. Expected ui/serve.py[/red]")
        return

    console.print(f"[green]Starting UI on http://127.0.0.1:{port}[/green]")
    sp.run([sys.executable, str(ui_script), str(port)])


@main.command()
@click.pass_context
def stats(ctx):
    """Show statistics about your venvs"""
    json_mode = _is_json_mode(ctx)
    from venvy.registry import VenvRegistry

    registry = VenvRegistry()
    stats_data = registry.get_stats()

    if json_mode:
        _output_result(stats_data)
    else:
        console.print(Panel.fit(f"""
[bold cyan]Virtual Environment Statistics[/bold cyan]

Total Environments: {stats_data['total_venvs']}
Total Disk Space:   {stats_data['total_size_mb']:.1f} MB
Total Packages:     {stats_data['total_packages']}

Unused 30+ days:    {stats_data['unused_30_days']}
Unused 90+ days:    {stats_data['unused_90_days']}
"""))


# ============================================================================
# ENVIRONMENT CONTROL COMMANDS (Agent-Safe!)
# ============================================================================

@main.command()
@click.option('--python', 'python_version', help='Python version (e.g., 3.11)')
@click.option('--packages', help='Space-separated packages to install')
@click.option('--requirements', '-r', type=click.Path(exists=True, path_type=Path),
              help='Requirements file')
@click.option('--name', '-n', help='Environment name')
@click.option('--path', '-p', type=click.Path(path_type=Path), help='Environment path')
@click.pass_context
def ensure(ctx, python_version, packages, requirements, name, path):
    """Ensure environment exists with required packages (idempotent)

    Creates the environment if it doesn't exist, verifies it if it does.
    Reads venvy.json from project root if it exists.

    Examples:
        venvy ensure
        venvy ensure --python 3.11 --packages "requests flask"
        venvy ensure --requirements requirements.txt --json
    """
    json_mode = _is_json_mode(ctx)
    from venvy.env_manager import EnvironmentManager

    mgr = EnvironmentManager()
    pkg_list = packages.split() if packages else None

    result = mgr.ensure_environment(
        path=path, name=name, python_version=python_version,
        packages=pkg_list, requirements=requirements,
        project_path=Path.cwd()
    )

    if json_mode:
        _output_result(result, result.get("_exit_code", ExitCode.SUCCESS))
    else:
        status = result.get("status", "unknown")
        env_path = result.get("path", "?")
        py_ver = result.get("python_version", "?")

        if result.get("_exit_code", 0) != 0:
            console.print(f"[red]Error:[/red] {result.get('error', 'Unknown error')}")
            sys.exit(result.get("_exit_code", ExitCode.GENERAL_ERROR))

        if status == "created":
            console.print(f"[green]Created new environment[/green]")
        elif status == "updated":
            console.print(f"[green]Updated existing environment[/green]")
        else:
            console.print(f"[green]Environment verified[/green]")

        console.print(f"  Path: {env_path}")
        console.print(f"  Python: {py_ver}")
        if result.get("packages_installed"):
            console.print(f"  Packages installed: {', '.join(result['packages_installed'])}")


@main.command('safe-install')
@click.argument('packages', nargs=-1)
@click.option('--requirements', '-r', type=click.Path(exists=True, path_type=Path),
              help='Requirements file')
@click.option('--env', 'env_path', type=click.Path(exists=True, path_type=Path),
              help='Environment path (default: auto-detect)')
@click.option('--checkpoint-name', help='Name for the auto-checkpoint')
@click.pass_context
def safe_install(ctx, packages, requirements, env_path, checkpoint_name):
    """Install packages with automatic checkpoint and rollback

    Creates a checkpoint before installing. If the install fails,
    automatically rolls back to the previous state.

    Examples:
        venvy safe-install requests flask
        venvy safe-install -r requirements.txt --json
        venvy safe-install numpy pandas --env .venv
    """
    json_mode = _is_json_mode(ctx)
    from venvy.env_manager import EnvironmentManager

    if env_path is None:
        env_path = _auto_detect_env()

    if env_path is None:
        if json_mode:
            _output_result({"error": "No environment found. Run 'venvy ensure' first."},
                           ExitCode.ENV_NOT_FOUND)
        console.print("[red]No environment found. Run 'venvy ensure' first.[/red]")
        sys.exit(ExitCode.ENV_NOT_FOUND)

    mgr = EnvironmentManager()
    result = mgr.safe_install(
        env_path=env_path,
        packages=list(packages) if packages else None,
        requirements=requirements,
        checkpoint_name=checkpoint_name,
    )

    if json_mode:
        _output_result(result, result.get("_exit_code", ExitCode.SUCCESS))
    else:
        status = result.get("status", "unknown")
        if status == "success":
            console.print("[green]Packages installed successfully[/green]")
            if result.get("installed"):
                console.print(f"  Installed: {', '.join(result['installed'])}")
            console.print(f"  Checkpoint: {result.get('checkpoint_name', '?')}")
        elif status == "rolled_back":
            console.print("[yellow]Installation failed - rolled back to checkpoint[/yellow]")
            console.print(f"  Error: {result.get('error', 'Unknown')}")
        else:
            console.print(f"[red]Installation failed:[/red] {result.get('error', 'Unknown')}")
            sys.exit(result.get("_exit_code", ExitCode.GENERAL_ERROR))


@main.command()
@click.option('--name', '-n', help='Checkpoint name (auto-generated if omitted)')
@click.option('--env', 'env_path', type=click.Path(exists=True, path_type=Path),
              help='Environment path (default: auto-detect)')
@click.pass_context
def checkpoint(ctx, name, env_path):
    """Create a snapshot of current environment state

    Examples:
        venvy checkpoint
        venvy checkpoint --name "before-upgrade" --json
        venvy checkpoint --env .venv
    """
    json_mode = _is_json_mode(ctx)
    from venvy.env_manager import EnvironmentManager

    if env_path is None:
        env_path = _auto_detect_env()

    if env_path is None:
        if json_mode:
            _output_result({"error": "No environment found"}, ExitCode.ENV_NOT_FOUND)
        console.print("[red]No environment found[/red]")
        sys.exit(ExitCode.ENV_NOT_FOUND)

    mgr = EnvironmentManager()
    result = mgr.create_checkpoint(env_path=env_path, name=name)

    if json_mode:
        _output_result(result, result.get("_exit_code", ExitCode.SUCCESS))
    else:
        if result.get("_exit_code", 0) != 0:
            console.print(f"[red]Error:[/red] {result.get('error', 'Unknown')}")
            sys.exit(result.get("_exit_code", ExitCode.GENERAL_ERROR))

        console.print(f"[green]Checkpoint created[/green]")
        console.print(f"  Name: {result.get('name', '?')}")
        console.print(f"  Packages: {result.get('package_count', '?')}")
        console.print(f"  ID: {result.get('checkpoint_id', '?')}")


@main.command()
@click.option('--checkpoint', 'checkpoint_name', help='Checkpoint name to restore')
@click.option('--latest', is_flag=True, help='Use most recent checkpoint')
@click.option('--env', 'env_path', type=click.Path(exists=True, path_type=Path),
              help='Environment path (default: auto-detect)')
@click.pass_context
def rollback(ctx, checkpoint_name, latest, env_path):
    """Restore environment to a checkpoint state

    Examples:
        venvy rollback --latest --json
        venvy rollback --checkpoint "before-upgrade"
        venvy rollback --latest --env .venv
    """
    json_mode = _is_json_mode(ctx)
    from venvy.env_manager import EnvironmentManager

    if env_path is None:
        env_path = _auto_detect_env()

    if env_path is None:
        if json_mode:
            _output_result({"error": "No environment found"}, ExitCode.ENV_NOT_FOUND)
        console.print("[red]No environment found[/red]")
        sys.exit(ExitCode.ENV_NOT_FOUND)

    if not checkpoint_name and not latest:
        if json_mode:
            _output_result({"error": "Specify --checkpoint NAME or --latest"}, ExitCode.GENERAL_ERROR)
        console.print("[red]Specify --checkpoint NAME or --latest[/red]")
        sys.exit(ExitCode.GENERAL_ERROR)

    mgr = EnvironmentManager()
    result = mgr.rollback_to_checkpoint(
        env_path=env_path,
        checkpoint_name=checkpoint_name,
        use_latest=latest,
    )

    if json_mode:
        _output_result(result, result.get("_exit_code", ExitCode.SUCCESS))
    else:
        if result.get("_exit_code", 0) != 0:
            console.print(f"[red]Error:[/red] {result.get('error', 'Unknown')}")
            sys.exit(result.get("_exit_code", ExitCode.GENERAL_ERROR))

        console.print(f"[green]Rolled back to checkpoint: {result.get('checkpoint_used', '?')}[/green]")
        if result.get("packages_added"):
            console.print(f"  Reinstalled: {', '.join(result['packages_added'])}")
        if result.get("packages_removed"):
            console.print(f"  Removed: {', '.join(result['packages_removed'])}")


@main.command()
@click.option('--python', 'python_version', help='Python version (e.g., 3.11)')
@click.option('--no-hook', 'no_hook', is_flag=True, help='Skip pip wrapper hook installation')
@click.option('--no-claude-md', 'no_claude_md', is_flag=True, help='Skip CLAUDE.md generation')
@click.option('--no-pip-config', 'no_pip_config', is_flag=True, help='Skip pip.ini configuration')
@click.option('--force', '-f', is_flag=True, help='Overwrite existing CLAUDE.md/venvy.json')
@click.pass_context
def init(ctx, python_version, no_hook, no_claude_md, no_pip_config, force):
    """Initialize venvy observability for this project (one-time setup)

    Sets up virtual environment, pip monitoring hook, CLAUDE.md agent
    instructions, and venvy.json project config.

    Examples:
        venvy init
        venvy init --python 3.11
        venvy init --no-hook --json
    """
    json_mode = _is_json_mode(ctx)

    from venvy.init_manager import InitManager

    mgr = InitManager()

    if not json_mode:
        console.print("[bold]Initializing venvy for this project...[/bold]\n")

    result = mgr.initialize_project(
        project_path=Path("."),
        python_version=python_version,
        install_hook=not no_hook,
        generate_claude=not no_claude_md,
        configure_pip=not no_pip_config,
        force=force,
    )

    exit_code = result.get("_exit_code", ExitCode.SUCCESS)
    steps = result.get("steps", {})

    if json_mode:
        output = {k: v for k, v in steps.items()}
        _output_result(output, exit_code)
    else:
        for step_name, step_result in steps.items():
            status = step_result.get("status", "unknown")
            detail = step_result.get("detail", "")
            if status == "created":
                console.print(f"  [green]CREATED[/green] {step_name}: {detail}")
            elif status == "skipped":
                console.print(f"  [yellow]SKIPPED[/yellow] {step_name}: {detail}")
            elif status == "verified":
                console.print(f"  [green]OK[/green] {step_name}: {detail}")
            elif status == "error":
                console.print(f"  [red]ERROR[/red] {step_name}: {detail}")
            else:
                console.print(f"  [dim]{status}[/dim] {step_name}: {detail}")

        console.print("\n[green bold]venvy initialized![/green bold] Pip installs are now monitored.")
        console.print("[dim]Run 'venvy status --json' to check environment health.[/dim]")


@main.command('_pip-event', hidden=True)
@click.option('--before', 'is_before', is_flag=True)
@click.option('--after', 'is_after', is_flag=True)
@click.option('--action', type=click.Choice(['install', 'uninstall']), default='install')
@click.option('--packages', default='')
@click.option('--exit-code', 'pip_exit_code', type=int, default=0)
@click.pass_context
def pip_event(ctx, is_before, is_after, action, packages, pip_exit_code):
    """Internal: called by pip wrapper to log install/uninstall events."""
    json_mode = _is_json_mode(ctx)

    env_path_str = os.environ.get('VIRTUAL_ENV')
    if not env_path_str:
        if json_mode:
            _output_result({"skipped": True, "reason": "no active venv"})
        return

    env_path = Path(env_path_str)
    context_file = env_path / ".venvy_pip_context.json"

    from venvy.pip_observer import PipObserver

    observer = PipObserver()

    if is_before:
        context = observer.before_event(env_path, action, packages)
        # Write context for --after to pick up
        try:
            context_file.write_text(json.dumps(context, default=str), encoding="utf-8")
        except Exception:
            pass
        if json_mode:
            _output_result({"phase": "before", "snapshot_taken": True})

    elif is_after:
        # Read context from --before
        context = {}
        if context_file.exists():
            try:
                context = json.loads(context_file.read_text(encoding="utf-8"))
                context_file.unlink()
            except Exception:
                pass

        result = observer.after_event(env_path, context, pip_exit_code, action, packages)
        if json_mode:
            _output_result(result)


@main.command()
@click.option('--env', 'env_path', type=click.Path(path_type=Path),
              help='Environment path (auto-detected if not specified)')
@click.pass_context
def status(ctx, env_path):
    """Show environment health and recent activity

    Returns a structured health report with recent pip events, alerts,
    disk usage, and overall health rating. Designed for agent consumption.

    Examples:
        venvy status --json
        venvy status --env .venv --json
    """
    json_mode = _is_json_mode(ctx)

    if env_path is None:
        env_path = _auto_detect_env()

    from venvy.pip_observer import PipObserver

    observer = PipObserver()
    report = observer.get_status_report(env_path)

    if json_mode:
        _output_result(report)
    else:
        health = report.get("health", "unknown")
        health_colors = {"good": "green", "warn": "yellow", "critical": "red"}
        color = health_colors.get(health, "dim")

        console.print(f"[bold]Environment Health:[/bold] [{color}]{health.upper()}[/{color}]")

        if report.get("env_path"):
            console.print(f"  Path: {report['env_path']}")
        if report.get("python_version"):
            console.print(f"  Python: {report['python_version']}")
        if report.get("total_size_mb") is not None:
            console.print(f"  Size: {report['total_size_mb']:.1f} MB")
        if report.get("package_count") is not None:
            console.print(f"  Packages: {report['package_count']}")

        # Recent events
        events = report.get("recent_events", [])
        if events:
            console.print(f"\n[bold]Recent Activity:[/bold] ({len(events)} events)")
            for e in events[:5]:
                action = e.get("action", "?")
                pkgs = e.get("packages", [])
                pkg_str = ", ".join(pkgs[:3]) if pkgs else "?"
                if pkgs and len(pkgs) > 3:
                    pkg_str += f" +{len(pkgs) - 3} more"
                delta = e.get("size_delta_mb")
                delta_str = f" (+{delta:.1f}MB)" if delta else ""
                console.print(f"  {action}: {pkg_str}{delta_str}")

        # Alerts
        alerts = report.get("alerts", [])
        if alerts:
            console.print(f"\n[bold]Alerts:[/bold]")
            for a in alerts:
                level = a.get("level", "info")
                msg = a.get("message", "?")
                level_color = {"warn": "yellow", "critical": "red"}.get(level, "dim")
                console.print(f"  [{level_color}]{level.upper()}[/{level_color}] {msg}")

        # Checkpoint info
        if report.get("last_checkpoint"):
            console.print(f"\n  Last checkpoint: {report['last_checkpoint']}")
            if report.get("events_since_checkpoint") is not None:
                console.print(f"  Events since: {report['events_since_checkpoint']}")


@main.command()
@click.option('--json', 'json_flag', is_flag=True, help='Output as JSON')
@click.option('--refresh', is_flag=True,
              help='Download the latest advisory database, then scan')
@click.option('--env', 'env_paths', type=click.Path(path_type=Path), multiple=True,
              help='Audit a specific environment (repeatable). Default: all known envs')
@click.option('--scan', is_flag=True,
              help='Also discover unregistered environments on disk')
@click.option('--include-toolchain', is_flag=True,
              help='Include pip/setuptools/wheel in findings and the exit code')
@click.option('--offline', is_flag=True,
              help='Never access the network; fail if no usable local database exists')
@click.pass_context
def audit(ctx, json_flag, refresh, env_paths, scan, include_toolchain, offline):
    """Audit environments for known-vulnerable and malicious packages.

    Scans every registered environment (or those given with --env) against a local
    advisory database compiled from OSV. On the FIRST run, if no database exists, one
    is downloaded automatically (one-time, ~30MB); every scan after that is fully
    offline. Application-dependency findings drive the exit code; pip/setuptools/wheel
    are reported but excluded from the gate unless --include-toolchain is passed.

    Exit codes: 0 clean · 20 vulnerable · 21 malicious · 22 stale/partial · 23 no database

    Examples:
        venvy audit                    # scans everything; auto-fetches the DB on first run
        venvy audit --refresh          # update the DB first, then scan
        venvy audit --json             # machine-readable, for CI / agents
        venvy audit --offline          # never touch the network; fail if no local DB
        venvy audit --env .venv        # a single environment
    """
    json_mode = _is_json_mode(ctx) or json_flag

    from venvy.audit import report as audit_report
    from venvy.audit.scanner import scan as run_scan
    from venvy.audit.db import AdvisoryDBError, default_db_path, refresh_database

    db_path = default_db_path()

    if refresh and offline:
        _fail_audit(json_mode, ExitCode.GENERAL_ERROR,
                    "--refresh and --offline are mutually exclusive")

    # --- refresh (explicit network update) -------------------------------
    if refresh:
        try:
            if json_mode or _is_quiet(ctx):
                refresh_database(db_path)
            else:
                # Plain status lines (no animated spinner: its Braille glyphs crash the
                # Windows legacy console's cp1252 encoder).
                console.print("[dim]Updating advisory database...[/dim]")
                rep = refresh_database(db_path)
                console.print(
                    "[green]Advisory database updated[/green] - %s advisories "
                    "(%s malicious)" % (rep.advisories, rep.malicious)
                )
        except Exception as exc:
            if not db_path.exists():
                # No usable DB and refresh failed: cannot honestly report anything.
                _fail_audit(json_mode, ExitCode.AUDIT_DB_MISSING,
                            "advisory database refresh failed and no local database "
                            "exists: %s" % exc)
            if not json_mode:
                console.print("[yellow]refresh failed (%s); using existing database"
                              "[/yellow]" % exc)

    # --- scan (auto-bootstrap the DB on first run) -----------------------
    # AdvisoryDB validates on open: a missing/corrupt/empty database raises
    # AdvisoryDBError. On first run (or to recover a corrupt DB) we auto-fetch a
    # one-time copy and retry — UNLESS --offline, or a refresh was already attempted.
    # If it still fails we map to a clean exit 23: never a traceback, never a silent
    # clean from an empty DB, in both human and JSON mode.
    targets = [Path(p) for p in env_paths] if env_paths else None

    def _do_scan():
        return run_scan(env_paths=targets, db_path=db_path, include_scan=scan)

    try:
        result = _do_scan()
    except AdvisoryDBError as exc:
        if offline or refresh:
            _fail_audit(json_mode, ExitCode.AUDIT_DB_MISSING, str(exc))
        try:
            _bootstrap_db(db_path, json_mode, ctx)
            result = _do_scan()
        except AdvisoryDBError as exc2:
            _fail_audit(json_mode, ExitCode.AUDIT_DB_MISSING, str(exc2))
        except Exception as exc2:  # network / build failure during bootstrap
            _fail_audit(json_mode, ExitCode.AUDIT_DB_MISSING,
                        "could not obtain an advisory database: %s - "
                        "check your connection or run `venvy audit --refresh`" % exc2)

    # First-run fallback: a fresh install has an empty registry, which would make the
    # headline command report nothing at all. Fall back to the environment in the
    # current directory (VIRTUAL_ENV / .venv / venv) so `venvy audit` is useful
    # immediately after `pip install venvy`.
    auto_detected = None
    if result.stats.envs_scanned == 0 and not targets and not scan:
        auto_detected = _auto_detect_env()
        if auto_detected:
            targets = [auto_detected]
            result = _do_scan()

    exit_code = audit_report.decide_exit_code(result, include_toolchain)

    if json_mode:
        payload = audit_report.build_json(result, exit_code)
        click.echo(json.dumps(payload, indent=2, default=str))
        sys.exit(exit_code)

    if auto_detected:
        console.print("[dim]No registered environments yet - auditing %s from the "
                      "current directory. Run `venvy audit --scan` to find others.[/dim]"
                      % auto_detected)
    elif result.stats.envs_scanned == 0 and not targets:
        console.print("[dim]No environments found. Activate a venv to register it, "
                      "or use `venvy audit --scan` to discover them on disk.[/dim]")
    audit_report.render_human(result, console, include_toolchain)
    sys.exit(exit_code)


@main.command()
@click.option('--apply', 'do_apply', is_flag=True,
              help='Actually deduplicate (default is a read-only dry run)')
@click.option('--env', 'env_paths', type=click.Path(path_type=Path), multiple=True,
              help='Deduplicate specific environments (repeatable). Default: all known envs')
@click.option('--min-size', type=int, default=None,
              help='Ignore files smaller than this many bytes (default: 4096)')
@click.option('--top', type=int, default=10, help='How many largest groups to list')
@click.pass_context
def dedup(ctx, do_apply, env_paths, min_size, top):
    """Reclaim disk space by hardlinking identical files across environments.

    Every environment installs its own byte-for-byte copy of the same wheels. This
    finds files that are provably identical across your environments and makes them
    share storage. Nothing is deleted and every environment keeps working.

    Read-only by default: run it bare to see what could be reclaimed, then --apply.

    Examples:
        venvy dedup                    # dry run: what would be reclaimed
        venvy dedup --apply            # collapse duplicates into hardlinks
        venvy dedup --env .venv --json # machine-readable, single environment
    """
    from venvy.dedup import (
        DEFAULT_MIN_SIZE, apply_dedup, enumerate_environments, find_duplicates,
    )

    json_mode = _is_json_mode(ctx)
    auto_yes = _is_auto_yes(ctx)
    threshold = DEFAULT_MIN_SIZE if min_size is None else min_size

    targets = [Path(p) for p in env_paths] if env_paths else None
    envs, enum_errors = enumerate_environments(targets)

    if not envs:
        msg = ("no environments found - activate a venv to register it, "
               "or pass --env <path>")
        if json_mode:
            _output_result({"error": msg, "environments": 0}, ExitCode.ENV_NOT_FOUND)
        console.print("[yellow]%s[/yellow]" % msg)
        sys.exit(ExitCode.ENV_NOT_FOUND)

    if not json_mode and not _is_quiet(ctx):
        console.print("[dim]Scanning %d environment(s) for duplicate files...[/dim]"
                      % len(envs))
    report = find_duplicates(envs, min_size=threshold)
    report.errors.extend(enum_errors)

    # --- apply ------------------------------------------------------------
    if do_apply and report.reclaimable_bytes > 0:
        if not auto_yes and not json_mode:
            console.print("This will replace %d duplicate file(s) with hardlinks, "
                          "reclaiming %s." % (
                              sum(len(g.paths) - 1 for g in report.groups),
                              human_readable_size(report.reclaimable_bytes)))
            if not Confirm.ask("Proceed?"):
                console.print("Cancelled")
                return
        report = apply_dedup(report, min_size=threshold)

    # --- output -----------------------------------------------------------
    if json_mode:
        _output_result({
            "applied": report.applied,
            "environments_scanned": report.envs_scanned,
            "files_scanned": report.files_scanned,
            "duplicate_groups": len(report.groups),
            "reclaimable_bytes": report.reclaimable_bytes,
            "already_shared_bytes": report.already_shared_bytes,
            "linked_files": report.linked_files,
            "reclaimed_bytes": report.reclaimed_bytes,
            "duration_ms": report.duration_ms,
            "errors": report.errors,
            "largest": [
                {"size": g.size, "copies": g.inodes,
                 "reclaimable": g.reclaimable, "example": g.paths[0]}
                for g in report.groups[:top]
            ],
        })

    if report.applied:
        console.print("[green]Reclaimed %s[/green] by hardlinking %d file(s) across "
                      "%d environment(s)." % (human_readable_size(report.reclaimed_bytes),
                                              report.linked_files, report.envs_scanned))
    elif report.reclaimable_bytes == 0:
        console.print("[green]Nothing to reclaim[/green] - scanned %d file(s) across "
                      "%d environment(s)." % (report.files_scanned, report.envs_scanned))
    else:
        console.print("[bold]%s reclaimable[/bold] across %d environment(s) "
                      "(%d duplicate group(s), %d files scanned in %dms)"
                      % (human_readable_size(report.reclaimable_bytes),
                         report.envs_scanned, len(report.groups),
                         report.files_scanned, report.duration_ms))
        if report.groups:
            table = Table(show_header=True, header_style="bold", box=None, pad_edge=False)
            table.add_column("reclaimable")
            table.add_column("size")
            table.add_column("copies")
            table.add_column("file")
            for g in report.groups[:top]:
                table.add_row(human_readable_size(g.reclaimable),
                              human_readable_size(g.size), str(g.inodes),
                              Path(g.paths[0]).name)
            console.print(table)
        console.print("[dim]Run `venvy dedup --apply` to reclaim it. "
                      "Nothing is deleted - duplicates become hardlinks.[/dim]")

    if report.already_shared_bytes:
        console.print("[dim]%s is already shared via existing hardlinks.[/dim]"
                      % human_readable_size(report.already_shared_bytes))
    for err in report.errors[:5]:
        console.print("[yellow]note:[/yellow] %s" % err)


def _fail_audit(json_mode: bool, exit_code: int, message: str):
    """Emit an audit error consistently in either output mode, then exit."""
    if json_mode:
        click.echo(json.dumps(
            {"schema_version": 1, "exit_code": exit_code, "success": False,
             "error": message}, indent=2))
    else:
        console.print("[red]%s[/red]" % message)
    sys.exit(exit_code)


def _bootstrap_db(db_path, json_mode: bool, ctx):
    """First-run: download a one-time advisory database, then let the caller retry.

    In JSON mode the human notice goes to STDERR so STDOUT stays valid JSON. Raises on
    network/build failure — the caller maps that to a clean exit 23.
    """
    from venvy.audit.db import refresh_database

    if json_mode:
        click.echo("venvy: no advisory database found; downloading a one-time copy "
                   "(~30MB)...", err=True)
        refresh_database(db_path)
        return
    if _is_quiet(ctx):
        refresh_database(db_path)
        return
    # Plain status lines (no animated spinner: its Braille glyphs crash the Windows
    # legacy console's cp1252 encoder).
    console.print("[dim]No advisory database found - downloading a one-time copy "
                  "(~30MB). Future scans are fully offline.[/dim]")
    rep = refresh_database(db_path)
    console.print("[green]Advisory database ready[/green] - %s advisories "
                  "(%s malicious)" % (rep.advisories, rep.malicious))


if __name__ == '__main__':
    main()
