"""
Rich display formatting for venvy
Beautiful tables, charts, and visual output for CLI
"""
from typing import List, Dict, Optional
from datetime import datetime

from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.progress import BarColumn, Progress
from rich.text import Text
from rich.columns import Columns
from rich.align import Align

from venvy.models import EnvironmentInfo, HealthStatus, CleanupSuggestion, SystemSummary, EnvironmentType
from venvy.utils import human_readable_size


class VenvyDisplay:
    """Handles rich visual display for venvy CLI"""
    
    def __init__(self, console: Console):
        self.console = console
    
    def show_environments_table(self, environments: List[EnvironmentInfo]):
        """Display environments in a rich table format"""
        table = Table(title="🐍 Python Virtual Environments", show_lines=True)
        
        # Add columns
        table.add_column("Environment", style="bold cyan", no_wrap=True)
        table.add_column("Type", justify="center", style="dim")
        table.add_column("Python", justify="center", style="green")
        table.add_column("Size", justify="right", style="yellow")
        table.add_column("Health", justify="center")
        table.add_column("Last Used", justify="center", style="dim")
        table.add_column("Path", style="dim", max_width=40)
        
        for env in environments:
            # Format health status with emoji
            health_display = self._format_health_status(env.health_status)
            
            # Format last used
            last_used = self._format_last_used(env.days_since_used)
            
            # Format size
            size_display = human_readable_size(env.size_bytes) if env.size_bytes else "Unknown"
            
            # Format type with emoji
            type_display = self._format_environment_type(env.type)
            
            table.add_row(
                env.name,
                type_display,
                env.python_version or "Unknown",
                size_display,
                health_display,
                last_used,
                str(env.path)
            )
        
        self.console.print(table)
        
        # Summary
        total_size = sum(env.size_bytes or 0 for env in environments)
        self.console.print(f"\n📊 Found {len(environments)} environment(s) using {human_readable_size(total_size)} total")
    
    def show_size_analysis(self, environments: List[EnvironmentInfo]):
        """Display size analysis with visual bars"""
        if not environments:
            return
        
        table = Table(title="💾 Environment Size Analysis", show_lines=True)
        table.add_column("Rank", justify="center", style="dim", width=4)
        table.add_column("Environment", style="bold cyan")
        table.add_column("Size", justify="right", style="yellow", width=10)
        table.add_column("Usage", width=20)
        table.add_column("Type", justify="center", style="dim", width=8)
        
        # Calculate max size for progress bar scaling
        max_size = max(env.size_bytes or 0 for env in environments)
        
        for i, env in enumerate(environments, 1):
            size_bytes = env.size_bytes or 0
            size_display = human_readable_size(size_bytes)
            
            # Create size bar
            if max_size > 0:
                bar_width = int((size_bytes / max_size) * 18)
                bar = "█" * bar_width + "░" * (18 - bar_width)
            else:
                bar = "░" * 18
            
            type_display = self._format_environment_type(env.type)
            
            table.add_row(
                str(i),
                env.name,
                size_display,
                f"[green]{bar}[/green]",
                type_display
            )
        
        self.console.print(table)
        
        # Show distribution
        self._show_size_distribution(environments)
    
    def show_environment_details(self, env: EnvironmentInfo):
        """Show detailed information about a single environment"""
        # Main info panel
        info_lines = []
        info_lines.append(f"📍 Path: {env.path}")
        info_lines.append(f"📦 Type: {self._format_environment_type(env.type)}")
        
        if env.python_version:
            info_lines.append(f"🐍 Python: {env.python_version}")
        
        if env.python_executable:
            info_lines.append(f"⚙️ Executable: {env.python_executable}")
        
        if env.size_bytes:
            info_lines.append(f"💾 Size: {human_readable_size(env.size_bytes)}")
        
        if env.package_count is not None:
            info_lines.append(f"📚 Packages: {env.package_count}")
        
        if env.pip_version:
            info_lines.append(f"📦 pip: {env.pip_version}")
        
        # Timestamps
        if env.created_date:
            info_lines.append(f"🗓️ Created: {env.created_date.strftime('%Y-%m-%d %H:%M')}")
        
        if env.days_since_used is not None:
            info_lines.append(f"⏰ Last used: {self._format_last_used(env.days_since_used)}")
        
        panel = Panel(
            "\n".join(info_lines),
            title=f"🐍 {env.name}",
            expand=False
        )
        self.console.print(panel)
        
        # Health status
        self._show_health_details(env)
        
        # Project associations
        if env.linked_projects:
            self.console.print("\n🔗 Linked Projects:")
            for project in env.linked_projects:
                self.console.print(f"   📁 {project}")
        elif env.is_orphaned:
            self.console.print("\n⚠️ No linked projects found (orphaned environment)")
        
        # Requirements files
        if env.requirements_files:
            self.console.print("\n📄 Requirements Files:")
            for req_file in env.requirements_files:
                self.console.print(f"   📝 {req_file}")
        
        # Packages (if not too many)
        if env.packages and len(env.packages) <= 20:
            self.console.print(f"\n📚 Installed Packages ({len(env.packages)}):")
            # Show in columns
            package_texts = [Text(pkg, style="dim") for pkg in sorted(env.packages)]
            columns = Columns(package_texts, equal=True, expand=True)
            self.console.print(columns)
        elif env.packages:
            self.console.print(f"\n📚 {len(env.packages)} packages installed (use 'venvy packages {env.name}' to see all)")
    
    def show_health_report(self, environments: List[EnvironmentInfo]):
        """Show health report for all environments"""
        # Categorize by health status
        health_categories = {
            HealthStatus.HEALTHY: [],
            HealthStatus.OUTDATED: [], 
            HealthStatus.WARNING: [],
            HealthStatus.BROKEN: [],
            HealthStatus.UNKNOWN: []
        }
        
        for env in environments:
            health_categories[env.health_status].append(env)
        
        # Summary stats
        total = len(environments)
        healthy = len(health_categories[HealthStatus.HEALTHY])
        issues = total - healthy
        
        summary_text = f"Health Report: {healthy}/{total} healthy environments"
        if issues > 0:
            summary_text += f" ({issues} with issues)"
        
        self.console.print(Panel(summary_text, style="bold"))
        
        # Show each category
        for status, envs in health_categories.items():
            if not envs:
                continue
            
            status_display = self._format_health_status(status)
            self.console.print(f"\n{status_display} {status.value.title()} ({len(envs)} environment(s))")
            
            for env in envs:
                line = f"  📁 {env.name}"
                if env.health_issues:
                    line += f" - {', '.join(env.health_issues)}"
                self.console.print(line)
    
    def show_cleanup_suggestions(self, suggestions: List[CleanupSuggestion]):
        """Display cleanup suggestions"""
        table = Table(title="💡 Cleanup Suggestions", show_lines=True)
        table.add_column("Environment", style="bold cyan")
        table.add_column("Reason", style="yellow", max_width=40)
        table.add_column("Space", justify="right", style="green")
        table.add_column("Risk", justify="center", style="dim")
        table.add_column("Confidence", justify="center", style="dim")
        
        total_space = 0
        for suggestion in suggestions:
            confidence_pct = int(suggestion.confidence * 100)
            confidence_display = f"{confidence_pct}%"
            
            risk_color = {
                "low": "green",
                "medium": "yellow", 
                "high": "red"
            }.get(suggestion.risk_level, "dim")
            
            table.add_row(
                suggestion.environment.name,
                suggestion.reason,
                suggestion.space_recovered_human,
                f"[{risk_color}]{suggestion.risk_level}[/{risk_color}]",
                confidence_display
            )
            
            total_space += suggestion.space_recovered
        
        self.console.print(table)
        
        if total_space > 0:
            self.console.print(f"\n💾 Potential space savings: [bold green]{human_readable_size(total_space)}[/bold green]")
            self.console.print("   💡 Use 'venvy clean' to automatically clean up safe suggestions")
    
    def show_system_summary(self, summary: SystemSummary, environments: List[EnvironmentInfo]):
        """Show system-wide statistics summary"""
        # Main statistics
        stats_text = f"📊 System Summary\n\n"
        stats_text += f"Total Environments: {summary.total_environments}\n"
        stats_text += f"Total Size: {summary.total_size_human}\n"
        
        if summary.potential_savings_bytes > 0:
            stats_text += f"Potential Savings: {summary.potential_savings_human}"
        
        self.console.print(Panel(stats_text, title="🐍 venvy Statistics", expand=False))
        
        # Environment types distribution
        if summary.environment_types:
            self.console.print("\n📦 Environment Types:")
            for env_type, count in summary.environment_types.items():
                percentage = (count / summary.total_environments) * 100
                bar_width = int((count / summary.total_environments) * 20)
                bar = "█" * bar_width + "░" * (20 - bar_width)
                type_display = self._format_environment_type(EnvironmentType(env_type))
                self.console.print(f"  {type_display} {env_type:<12} {count:>3} [green]{bar}[/green] {percentage:>5.1f}%")
        
        # Health distribution
        if summary.health_distribution:
            self.console.print("\nHealth Distribution:")
            for health, count in summary.health_distribution.items():
                percentage = (count / summary.total_environments) * 100
                bar_width = int((count / summary.total_environments) * 20)
                bar = "█" * bar_width + "░" * (20 - bar_width)
                health_status = HealthStatus(health)
                status_display = self._format_health_status(health_status)
                self.console.print(f"  {status_display} {health:<12} {count:>3} [green]{bar}[/green] {percentage:>5.1f}%")
        
        # Notable environments
        if summary.largest_environment:
            self.console.print(f"\n📈 Largest: {summary.largest_environment.name} ({human_readable_size(summary.largest_environment.size_bytes or 0)})")
        
        if summary.most_used_environment and summary.most_used_environment.activation_count:
            self.console.print(f"🔥 Most Used: {summary.most_used_environment.name} ({summary.most_used_environment.activation_count} activations)")
        
        if summary.oldest_environment and summary.oldest_environment.created_date:
            days_old = (datetime.now() - summary.oldest_environment.created_date).days
            self.console.print(f"⏰ Oldest: {summary.oldest_environment.name} ({days_old} days old)")
    
    def show_duplicate_environments(self, duplicate_groups: List[List[EnvironmentInfo]]):
        """Show duplicate environment groups"""
        self.console.print(f"Found {len(duplicate_groups)} group(s) of similar environments:\n")
        
        total_potential_savings = 0
        
        for i, group in enumerate(duplicate_groups, 1):
            # Calculate total size of group
            group_size = sum(env.size_bytes or 0 for env in group)
            largest_env = max(group, key=lambda e: e.size_bytes or 0)
            potential_savings = group_size - (largest_env.size_bytes or 0)
            total_potential_savings += potential_savings
            
            self.console.print(f"[bold]Group {i}:[/bold] {len(group)} similar environment(s)")
            
            for env in group:
                size_display = human_readable_size(env.size_bytes or 0)
                is_largest = env == largest_env
                marker = "[L]" if is_largest else "[D]"
                self.console.print(f"  {marker} {env.name:<20} {size_display:>10} {env.path}")
            
            if potential_savings > 0:
                self.console.print(f"  💾 Potential savings: {human_readable_size(potential_savings)}")
            
            self.console.print()
        
        if total_potential_savings > 0:
            self.console.print(f"💡 Total potential savings by removing duplicates: [bold green]{human_readable_size(total_potential_savings)}[/bold green]")
    
    def _format_health_status(self, status: HealthStatus) -> str:
        """Format health status with emoji"""
        status_map = {
            HealthStatus.HEALTHY: "✅",
            HealthStatus.OUTDATED: "⚠️",
            HealthStatus.WARNING: "🔶", 
            HealthStatus.BROKEN: "💀",
            HealthStatus.UNKNOWN: "❓"
        }
        return status_map.get(status, "❓")
    
    def _format_environment_type(self, env_type: EnvironmentType) -> str:
        """Format environment type with emoji"""
        type_map = {
            EnvironmentType.VENV: "📦",
            EnvironmentType.CONDA: "🐍",
            EnvironmentType.PYENV: "🔧",
            EnvironmentType.VIRTUALENV: "📁", 
            EnvironmentType.UNKNOWN: "❓"
        }
        return type_map.get(env_type, "❓")
    
    def _format_last_used(self, days_since_used: Optional[int]) -> str:
        """Format last used time"""
        if days_since_used is None:
            return "Unknown"
        elif days_since_used == 0:
            return "Today"
        elif days_since_used == 1:
            return "Yesterday"
        elif days_since_used < 7:
            return f"{days_since_used} days ago"
        elif days_since_used < 30:
            weeks = days_since_used // 7
            return f"{weeks} week(s) ago"
        elif days_since_used < 365:
            months = days_since_used // 30
            return f"{months} month(s) ago"
        else:
            years = days_since_used // 365
            return f"{years} year(s) ago"
    
    def _show_health_details(self, env: EnvironmentInfo):
        """Show detailed health information"""
        health_display = self._format_health_status(env.health_status)
        health_text = f"Health: {health_display} {env.health_status.value.title()}"
        
        if env.health_issues:
            health_text += "\nIssues:"
            for issue in env.health_issues:
                health_text += f"\n  • {issue}"
        
        health_color = {
            HealthStatus.HEALTHY: "green",
            HealthStatus.OUTDATED: "yellow",
            HealthStatus.WARNING: "yellow",
            HealthStatus.BROKEN: "red",
            HealthStatus.UNKNOWN: "dim"
        }.get(env.health_status, "dim")
        
        panel = Panel(health_text, title="Health Status", style=health_color, expand=False)
        self.console.print(panel)
    
    def _show_size_distribution(self, environments: List[EnvironmentInfo]):
        """Show size distribution chart"""
        size_categories = {
            "Tiny (< 50MB)": [],
            "Small (50-200MB)": [], 
            "Medium (200-500MB)": [],
            "Large (500MB-1GB)": [],
            "Huge (> 1GB)": []
        }
        
        for env in environments:
            if env.size_bytes is None:
                continue
            
            size_mb = env.size_bytes / (1024 * 1024)
            
            if size_mb < 50:
                size_categories["Tiny (< 50MB)"].append(env)
            elif size_mb < 200:
                size_categories["Small (50-200MB)"].append(env)
            elif size_mb < 500:
                size_categories["Medium (200-500MB)"].append(env)
            elif size_mb < 1024:
                size_categories["Large (500MB-1GB)"].append(env)
            else:
                size_categories["Huge (> 1GB)"].append(env)
        
        self.console.print("\n📊 Size Distribution:")
        total_with_size = sum(len(envs) for envs in size_categories.values())
        
        for category, envs in size_categories.items():
            if total_with_size > 0:
                percentage = (len(envs) / total_with_size) * 100
                bar_width = int((len(envs) / total_with_size) * 20) if total_with_size > 0 else 0
                bar = "█" * bar_width + "░" * (20 - bar_width)
                self.console.print(f"  {category:<20} {len(envs):>3} [green]{bar}[/green] {percentage:>5.1f}%")