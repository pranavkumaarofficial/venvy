# venvy - Python Virtual Environment Manager

**The smartest way to manage Python virtual environments**

[![PyPI](https://img.shields.io/pypi/v/venvy.svg)](https://pypi.org/project/venvy/)
[![Python](https://img.shields.io/pypi/pyversions/venvy.svg)](https://pypi.org/project/venvy/)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](https://github.com/pranavkumaarofficial/venvy/blob/main/LICENSE)

## What is venvy?

**venvy** is an intelligent command-line tool that automatically discovers, analyzes, and manages Python virtual environments across your entire system. Stop manually hunting for forgotten environments, wondering which ones are safe to delete, or struggling with disk space issues.

### Key Features

- **🔍 Smart Discovery** - Automatically finds all Python environments (venv, conda, pyenv, virtualenv)
- **📊 Intelligent Analysis** - Shows usage patterns, disk space, health status, and cleanup suggestions  
- **🧹 Safe Cleanup** - Remove unused environments with confidence using AI-powered recommendations
- **💾 Space Management** - Identify space hogs and duplicate environments
- **🏥 Health Monitoring** - Detect broken, outdated, or corrupted environments
- **🎨 Beautiful Interface** - Rich terminal output with tables, progress bars, and colors
- **⚡ Cross-Platform** - Works seamlessly on Windows, macOS, and Linux

## Installation

```bash
pip install venvy
```

That's it! No complex setup, no configuration files needed.

## Quick Start

```bash
# List all virtual environments
venvy list

# Show disk usage analysis  
venvy size

# Get intelligent cleanup suggestions
venvy suggest

# Remove unused environments safely
venvy clean --unused 90

# Get detailed info about an environment
venvy info myproject-env
```

## Why Choose venvy?

### Problem: Virtual Environment Chaos
- Forgotten environments scattered across your system
- Gigabytes of disk space wasted on unused environments
- No easy way to identify which environments are safe to remove
- Broken environments that cause mysterious errors
- Time wasted manually hunting for environment locations

### Solution: Intelligent Management
venvy solves these problems with smart automation:

```bash
$ venvy list
Environment         Type    Python    Size      Health      Last Used    
project1-venv       venv    3.9.7     245 MB    Healthy     2 days ago   
old-django-project  venv    3.8.0     1.2 GB    Broken      4 months ago 
data-science        conda   3.10.2    892 MB    Healthy     1 week ago   
temp-test           venv    3.9.7     156 MB    Outdated    6 months ago 

$ venvy suggest
Cleanup Suggestions:
Environment         Reason                           Space    Risk    Confidence
old-django-project  Broken and unused for 120 days  1.2 GB   Low     95%
temp-test          Unused for 180 days              156 MB   Low     87%

Potential space savings: 1.4 GB
```

## Core Commands

### Environment Discovery
```bash
venvy list                    # List all environments
venvy list --type conda      # Filter by type (venv, conda, pyenv)  
venvy list --sort size       # Sort by size, age, or usage
venvy list --format json     # Machine-readable output
```

### Space Analysis
```bash
venvy size                    # Show environments by size
venvy size --top 5           # Show 5 largest environments
venvy duplicates             # Find similar environments
```

### Health & Maintenance
```bash
venvy health                 # Overall health report
venvy doctor myenv           # Deep health check for specific environment
venvy stats                  # System-wide statistics
```

### Smart Cleanup
```bash
venvy suggest                # Get cleanup recommendations
venvy clean --unused 30      # Remove environments unused for 30+ days
venvy clean --dry-run        # Preview what would be removed
venvy remove myenv           # Remove specific environment
```

## Advanced Features

### Intelligent Analysis
venvy doesn't just list environments - it provides insights:

- **Usage Tracking**: Knows which environments you actually use
- **Health Monitoring**: Detects broken Python executables, missing dependencies
- **Space Optimization**: Identifies duplicate packages and cache bloat  
- **Project Association**: Links environments to their projects automatically
- **Security Scanning**: Finds environments with outdated packages

### Safe Operations
Every destructive operation includes safety measures:

- **Automatic Backups**: Creates backups before removal
- **Confidence Scoring**: AI-powered risk assessment for cleanup suggestions
- **Dry Run Mode**: Preview changes before applying them
- **Confirmation Prompts**: Prevents accidental deletions

### Professional Output
Beautiful, informative displays that work great in terminals and CI/CD:

- **Rich Tables**: Sortable columns with color-coded health indicators
- **Progress Bars**: Visual feedback for long operations
- **JSON Export**: Perfect for scripting and automation
- **Cross-Platform**: Consistent experience across operating systems

## Use Cases

### For Individual Developers
- **Clean up development machine**: Remove old project environments safely
- **Disk space management**: Identify and remove space-wasting environments
- **Environment health**: Find and fix broken development environments
- **Project organization**: See which environments belong to which projects

### For Development Teams  
- **Standardize environment management**: Consistent cleanup policies across team
- **CI/CD integration**: Automated environment cleanup in build pipelines
- **Onboarding**: Help new developers clean up their development setup
- **Documentation**: Generate environment inventory reports

### For System Administrators
- **Server maintenance**: Clean up unused environments on shared development servers
- **Disk space monitoring**: Proactive identification of space usage issues
- **Environment auditing**: Security and compliance reporting
- **Automated cleanup**: Scheduled cleanup of unused environments

## Technical Details

### Supported Environment Types
- **venv** - Python 3.3+ built-in virtual environments
- **virtualenv** - Traditional virtual environment tool
- **conda** - Anaconda/Miniconda environments
- **pyenv** - Python version management environments

### Detection Methods
- **Smart Scanning**: Looks in common locations (`~/venvs`, `~/.virtualenvs`, etc.)
- **Configuration Files**: Reads `pyvenv.cfg`, `conda-meta/`, `.python-version`
- **Custom Paths**: Supports user-defined search locations
- **Symbolic Link Resolution**: Handles complex directory structures

### Performance Optimizations
- **Parallel Processing**: Multi-threaded environment scanning
- **Smart Caching**: Avoids re-analyzing unchanged environments  
- **Lazy Loading**: Only analyzes environments when needed
- **Memory Efficient**: Minimal memory footprint even with hundreds of environments

### Safety Features
- **Backup Creation**: Automatic backups before destructive operations
- **Permission Handling**: Graceful handling of permission-denied scenarios
- **Error Recovery**: Robust error handling and reporting
- **Verification**: Confirms successful operations

## Configuration

venvy works perfectly out-of-the-box, but can be customized:

```bash
# Add custom search paths
venvy config --add-path ~/my-projects/envs

# Set default cleanup threshold
venvy config --set default-unused-days 60

# Configure output format
venvy config --set output-format table
```

Configuration is stored in your system's standard config directory and syncs across sessions.

## Python Virtual Environment Management Best Practices

venvy embodies Python virtual environment best practices:

1. **Regular Cleanup**: Remove unused environments to free disk space
2. **Health Monitoring**: Keep environments updated and functional
3. **Organization**: Maintain clear project-environment associations
4. **Documentation**: Know what environments you have and why
5. **Automation**: Use tools like venvy instead of manual management

## FAQ

**Q: Is it safe to use venvy to delete environments?**  
A: Yes! venvy creates automatic backups and uses confidence scoring to ensure safe cleanup recommendations.

**Q: Will venvy work with my existing environments?**  
A: Absolutely. venvy works with all standard Python environment tools and doesn't modify your existing setup.

**Q: Can I use venvy in scripts or CI/CD?**  
A: Yes! venvy supports JSON output, quiet modes, and non-interactive operation perfect for automation.

**Q: Does venvy require admin/root privileges?**  
A: No. venvy only needs access to your user directories and respects file permissions.

## Contributing

We welcome contributions! venvy is open source and community-driven.

- **Bug Reports**: [GitHub Issues](https://github.com/pranavkumaarofficial/venvy/issues)
- **Feature Requests**: [GitHub Discussions](https://github.com/pranavkumaarofficial/venvy/discussions)
- **Code Contributions**: [Pull Requests](https://github.com/pranavkumaarofficial/venvy/pulls)

## License

MIT License - see [LICENSE](LICENSE) file for details.

## Keywords

Python virtual environment manager, venv cleanup, conda environment management, Python development tools, disk space cleanup, environment health monitoring, Python project management, development workflow optimization, virtual environment discovery, Python environment analysis

---

**Made with ❤️ by [Pranav Kumaar](https://github.com/pranavkumaarofficial)**

*venvy - Because managing Python virtual environments should be intelligent, not manual.*