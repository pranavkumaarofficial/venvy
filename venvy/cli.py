"""
Command-line interface for venvy
Provides beautiful, intuitive commands for managing Python virtual environments
"""
import sys
import json
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
from venvy import __version__


# Global console for rich output - disable emoji on Windows for compatibility
import sys
console = Console(emoji=not sys.platform.startswith('win'))
display = VenvyDisplay(console)


@click.group()
@click.version_option(version=__version__, prog_name="venvy")
@click.option('--verbose', '-v', is_flag=True, help='Enable verbose output')
@click.pass_context
def main(ctx, verbose):
    """
    venvy - Intelligent Python Virtual Environment Manager
    
    Discover, analyze, and manage Python virtual environments with intelligence and style.
    """
    ctx.ensure_object(dict)
    ctx.obj['verbose'] = verbose
    
    if verbose:
        console.print(f"[dim]venvy v{__version__} on {get_platform_info()['system']}[/dim]")


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
    
    discovery = EnvironmentDiscovery()
    analysis = EnvironmentAnalysis()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        # Discovery phase
        discover_task = progress.add_task("Discovering environments...", total=None)
        
        # Use appropriate scanning mode
        use_fast_scan = fast and not thorough
        
        search_paths = [path] if path else None
        environments = discovery.discover_all(search_paths, use_fast_scan=use_fast_scan)
        
        progress.update(discover_task, description="Discovery complete")
        
        # Analysis phase with parallel processing
        if environments:
            analyze_task = progress.add_task("Analyzing environments...", total=len(environments))
            
            # Use parallel analysis for better performance
            environments = analysis.analyze_all_environments(environments, use_parallel=use_fast_scan)
            progress.update(analyze_task, advance=len(environments))
    
    # Filter by type if specified
    if env_type:
        env_type_enum = EnvironmentType(env_type.lower())
        environments = [env for env in environments if env.type == env_type_enum]
    
    # Sort environments
    environments = _sort_environments(environments, sort_by)
    
    if not environments:
        console.print("No Python virtual environments found.")
        if path:
            console.print(f"   Searched in: {path}")
        console.print("   Try running without filters or check different locations.")
        return
    
    # Display results
    if output_format == 'json':
        _output_json(environments)
    elif output_format == 'simple':
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
    
    discovery = EnvironmentDiscovery()
    analysis = EnvironmentAnalysis()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Analyzing environment sizes...", total=None)
        
        search_paths = [path] if path else None
        environments = discovery.discover_all(search_paths)
        environments = analysis.analyze_all_environments(environments)
        
        progress.update(task, description="Analysis complete")
    
    if not environments:
        console.print("No environments found to analyze.")
        return
    
    # Sort by size (largest first)
    environments = sorted(environments, key=lambda e: e.size_bytes or 0, reverse=True)
    
    # Limit to top N
    if top and len(environments) > top:
        environments = environments[:top]
    
    if output_format == 'json':
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
    
    if not environment:
        console.print("Please specify an environment name or path")
        console.print("   Example: venvy info myenv")
        return
    
    discovery = EnvironmentDiscovery()
    analysis = EnvironmentAnalysis()
    
    # Try to find the environment
    env_info = discovery.find_environment(environment)
    
    if not env_info:
        console.print(f"❌ Environment '{environment}' not found")
        return
    
    # Analyze the environment
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("🔍 Analyzing environment...", total=None)
        analyzed_env = analysis.analyze_environment(env_info)
        progress.update(task, description="✅ Analysis complete")
    
    display.show_environment_details(analyzed_env)


@main.command()
@click.option('--path', '-p', type=click.Path(exists=True, path_type=Path),
              help='Search path for environments')
@click.pass_context
def health(ctx, path):
    """Check health status of all environments"""
    
    discovery = EnvironmentDiscovery()
    analysis = EnvironmentAnalysis()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("Checking environment health...", total=None)
        
        search_paths = [path] if path else None
        environments = discovery.discover_all(search_paths)
        environments = analysis.analyze_all_environments(environments)
        
        progress.update(task, description="✅ Health check complete")
    
    if not environments:
        console.print("🤔 No environments found to check.")
        return
    
    display.show_health_report(environments)


@main.command()
@click.option('--path', '-p', type=click.Path(exists=True, path_type=Path),
              help='Search path for environments')
@click.option('--max-suggestions', '-n', type=int, default=10,
              help='Maximum number of suggestions to show')
@click.pass_context
def suggest(ctx, path, max_suggestions):
    """💡 Get intelligent cleanup suggestions"""
    
    discovery = EnvironmentDiscovery()
    analysis = EnvironmentAnalysis()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("🧠 Generating suggestions...", total=None)
        
        search_paths = [path] if path else None
        environments = discovery.discover_all(search_paths)
        environments = analysis.analyze_all_environments(environments)
        
        suggestions = analysis.generate_cleanup_suggestions(environments)
        
        progress.update(task, description="✅ Analysis complete")
    
    if not suggestions:
        console.print("🎉 No cleanup suggestions needed! Your environments look good.")
        return
    
    # Limit suggestions
    if max_suggestions and len(suggestions) > max_suggestions:
        suggestions = suggestions[:max_suggestions]
    
    display.show_cleanup_suggestions(suggestions)


@main.command()
@click.option('--path', '-p', type=click.Path(exists=True, path_type=Path),
              help='Search path for environments')
@click.pass_context
def stats(ctx, path):
    """📊 Show system-wide environment statistics"""
    
    discovery = EnvironmentDiscovery()
    analysis = EnvironmentAnalysis()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("📈 Gathering statistics...", total=None)
        
        search_paths = [path] if path else None
        environments = discovery.discover_all(search_paths)
        environments = analysis.analyze_all_environments(environments)
        
        summary = analysis.get_system_summary(environments)
        
        progress.update(task, description="✅ Statistics complete")
    
    display.show_system_summary(summary, environments)


@main.command()
@click.option('--path', '-p', type=click.Path(exists=True, path_type=Path),
              help='Search path for environments')
@click.pass_context
def duplicates(ctx, path):
    """Find environments with similar package lists"""
    
    discovery = EnvironmentDiscovery()
    analysis = EnvironmentAnalysis()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("🔍 Finding duplicate environments...", total=None)
        
        search_paths = [path] if path else None
        environments = discovery.discover_all(search_paths)
        environments = analysis.analyze_all_environments(environments)
        
        duplicate_groups = analysis.find_duplicate_environments(environments)
        
        progress.update(task, description="✅ Analysis complete")
    
    if not duplicate_groups:
        console.print("✨ No duplicate environments found!")
        return
    
    display.show_duplicate_environments(duplicate_groups)


@main.command()
@click.argument('environment')
@click.option('--force', '-f', is_flag=True, help='Skip confirmation prompt')
@click.pass_context
def remove(ctx, environment, force):
    """🗑️ Remove a specific environment"""
    
    discovery = EnvironmentDiscovery()
    
    # Find the environment
    env_info = discovery.find_environment(environment)
    
    if not env_info:
        console.print(f"❌ Environment '{environment}' not found")
        return
    
    # Show what will be removed
    console.print(f"📍 Found environment: [bold]{env_info.name}[/bold]")
    console.print(f"   Path: {env_info.path}")
    if env_info.size_bytes:
        console.print(f"   Size: {human_readable_size(env_info.size_bytes)}")
    
    # Confirm removal
    if not force:
        if not Confirm.ask(f"Are you sure you want to remove '{env_info.name}'?"):
            console.print("❌ Removal cancelled")
            return
    
    # Remove the environment using cleanup module
    cleanup = EnvironmentCleanup()
    success = cleanup.remove_environment(env_info, create_backup=True)
    
    if success:
        console.print(f"✅ Successfully removed '{env_info.name}'")
        if env_info.size_bytes:
            console.print(f"   Freed {human_readable_size(env_info.size_bytes)} of disk space")
        console.print("   💾 Backup created for safety")
    else:
        console.print(f"❌ Failed to remove environment")
        sys.exit(1)


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
    
    discovery = EnvironmentDiscovery()
    analysis = EnvironmentAnalysis()
    
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        console=console
    ) as progress:
        task = progress.add_task("🔍 Finding environments to clean...", total=None)
        
        search_paths = [path] if path else None
        environments = discovery.discover_all(search_paths)
        environments = analysis.analyze_all_environments(environments)
        
        # Find environments to clean
        to_remove = []
        for env in environments:
            if (env.days_since_used is not None and 
                env.days_since_used >= unused_days and
                env.health_status != HealthStatus.HEALTHY):
                to_remove.append(env)
        
        progress.update(task, description="✅ Analysis complete")
    
    if not to_remove:
        console.print(f"✨ No environments found that are unused for {unused_days}+ days")
        return
    
    # Show what will be removed
    total_size = sum(env.size_bytes or 0 for env in to_remove)
    
    console.print(f"\n🧹 Found {len(to_remove)} environment(s) to clean:")
    for env in to_remove:
        status_icon = "💀" if env.health_status == HealthStatus.BROKEN else "⚠️"
        console.print(f"   {status_icon} {env.name} ({human_readable_size(env.size_bytes or 0)}) - {env.days_since_used} days unused")
    
    console.print(f"\n💾 Total space to recover: [bold]{human_readable_size(total_size)}[/bold]")
    
    if dry_run:
        console.print("\n[dim]🔍 Dry run complete - no environments were actually removed[/dim]")
        return
    
    # Confirm removal
    if not force:
        if not Confirm.ask(f"Remove {len(to_remove)} environment(s)?"):
            console.print("❌ Cleanup cancelled")
            return
    
    # Remove environments using cleanup module
    cleanup = EnvironmentCleanup()
    results = cleanup.batch_remove_environments(to_remove, create_backups=True)
    
    removed_count = len(results['success'])
    failed_count = len(results['failed'])
    removed_size = sum(env.size_bytes or 0 for env in results['success'])
    
    # Show individual results
    for env in results['success']:
        console.print(f"✅ Removed {env.name}")
    
    for env in results['failed']:
        console.print(f"❌ Failed to remove {env.name}")
    
    console.print(f"\n🎉 Cleanup complete!")
    console.print(f"   Removed: {removed_count} environment(s)")
    if failed_count > 0:
        console.print(f"   Failed: {failed_count} environment(s)")
    console.print(f"   Space freed: {human_readable_size(removed_size)}")
    if removed_count > 0:
        console.print("   💾 Backups created for safety")


@main.command()
@click.option('--clear', is_flag=True, help='Clear all cached data')
@click.option('--stats', is_flag=True, help='Show cache statistics')
@click.pass_context
def cache(ctx, clear, stats):
    """Manage venvy cache for better performance"""
    from venvy.performance import EnvironmentCache
    
    cache_manager = EnvironmentCache()
    
    if clear:
        cache_manager.clear_cache()
        console.print("Cache cleared successfully")
        return
    
    if stats:
        cache_dir = cache_manager.cache_dir
        if cache_dir.exists():
            cache_files = list(cache_dir.glob("*.json"))
            total_size = sum(f.stat().st_size for f in cache_files if f.exists())
            
            console.print(f"Cache directory: {cache_dir}")
            console.print(f"Cache files: {len(cache_files)}")
            console.print(f"Total size: {human_readable_size(total_size)}")
            
            # Check cache freshness
            env_cache = cache_manager.cache_file
            if env_cache.exists():
                import json
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
            console.print("No cache data found")
        return
    
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


if __name__ == '__main__':
    main()