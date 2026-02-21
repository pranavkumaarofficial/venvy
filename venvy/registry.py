"""
Central registry for tracking virtual environments
No more slow filesystem scanning!
"""
import json
import sqlite3
from pathlib import Path
from typing import List, Dict, Optional
from datetime import datetime
from dataclasses import dataclass, asdict

from venvy.utils import get_venvy_data_dir, get_directory_size, find_python_executable, get_python_version


@dataclass
class VenvRecord:
    """Record of a virtual environment in the registry"""
    name: str
    path: str
    project_path: Optional[str] = None
    python_version: Optional[str] = None
    created_at: Optional[str] = None
    last_used_at: Optional[str] = None
    last_seen_at: Optional[str] = None
    size_mb: Optional[float] = None
    size_mb_cached_at: Optional[str] = None
    package_count: Optional[int] = None
    packages_cached_at: Optional[str] = None
    activation_count: Optional[int] = None
    missing: Optional[bool] = None
    is_active: bool = False
    notes: Optional[str] = None

    def to_dict(self) -> dict:
        """Convert to dictionary"""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> 'VenvRecord':
        """Create from dictionary"""
        return cls(**data)


class VenvRegistry:
    """
    Central registry for virtual environments

    Uses SQLite for fast queries without filesystem scanning
    """

    def __init__(self):
        self.data_dir = get_venvy_data_dir()
        self.db_path = self.data_dir / "venv_registry.db"
        self._init_db()

    def _init_db(self):
        """Initialize SQLite database"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS venvs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                path TEXT UNIQUE NOT NULL,
                project_path TEXT,
                python_version TEXT,
                created_at TEXT,
                last_used_at TEXT,
                last_seen_at TEXT,
                size_mb REAL,
                size_mb_cached_at TEXT,
                package_count INTEGER,
                packages_cached_at TEXT,
                activation_count INTEGER DEFAULT 0,
                missing INTEGER DEFAULT 0,
                is_active INTEGER DEFAULT 0,
                notes TEXT,
                registered_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes for fast lookups
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_name ON venvs(name)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_path ON venvs(path)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_project_path ON venvs(project_path)")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_last_used ON venvs(last_used_at)")

        self._ensure_columns(cursor)

        conn.commit()
        conn.close()

    def _ensure_columns(self, cursor: sqlite3.Cursor):
        """Ensure new columns exist for backwards compatibility"""
        cursor.execute("PRAGMA table_info(venvs)")
        existing = {row[1] for row in cursor.fetchall()}

        columns = {
            "last_seen_at": "TEXT",
            "size_mb_cached_at": "TEXT",
            "packages_cached_at": "TEXT",
            "activation_count": "INTEGER DEFAULT 0",
            "missing": "INTEGER DEFAULT 0",
        }

        for name, ddl in columns.items():
            if name not in existing:
                cursor.execute(f"ALTER TABLE venvs ADD COLUMN {name} {ddl}")

    def register(self, venv_path: Path, project_path: Optional[Path] = None,
                 name: Optional[str] = None) -> bool:
        """
        Register a new virtual environment

        Args:
            venv_path: Path to the venv directory
            project_path: Path to the project using this venv
            name: Custom name (defaults to venv directory name)

        Returns:
            True if registered successfully
        """
        venv_path = Path(venv_path).resolve()

        if not venv_path.exists():
            return False

        # Auto-detect name if not provided
        if name is None:
            name = venv_path.name

        # Get venv info
        python_exe = find_python_executable(venv_path)
        python_version = get_python_version(python_exe) if python_exe else None

        # Calculate size (async in background would be better)
        size_bytes = get_directory_size(venv_path)
        size_mb = size_bytes / (1024 * 1024) if size_bytes else None

        # Get package count
        package_count = self._count_packages(venv_path)

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                INSERT INTO venvs
                (name, path, project_path, python_version, created_at, last_used_at, last_seen_at,
                 size_mb, size_mb_cached_at, package_count, packages_cached_at, activation_count, missing)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(path) DO UPDATE SET
                    name = excluded.name,
                    project_path = excluded.project_path,
                    python_version = excluded.python_version,
                    last_used_at = excluded.last_used_at,
                    last_seen_at = excluded.last_seen_at,
                    size_mb = excluded.size_mb,
                    size_mb_cached_at = excluded.size_mb_cached_at,
                    package_count = excluded.package_count,
                    packages_cached_at = excluded.packages_cached_at
            """, (
                name,
                str(venv_path),
                str(project_path) if project_path else None,
                python_version,
                timestamp,
                timestamp,
                timestamp,
                size_mb,
                timestamp if size_mb is not None else None,
                package_count,
                timestamp if package_count is not None else None,
                0,
                0
            ))
            conn.commit()
            return True
        except Exception as e:
            print(f"Failed to register venv: {e}")
            return False
        finally:
            conn.close()

    def unregister(self, venv_path: Path) -> bool:
        """Remove venv from registry"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("DELETE FROM venvs WHERE path = ?", (str(venv_path),))
            conn.commit()
            return cursor.rowcount > 0
        finally:
            conn.close()

    def update_last_used(self, venv_path: Path, project_path: Optional[Path] = None):
        """Update last used timestamp and activation count"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cursor.execute("""
                UPDATE venvs SET last_used_at = ?,
                                 last_seen_at = ?,
                                 activation_count = COALESCE(activation_count, 0) + 1,
                                 project_path = COALESCE(?, project_path),
                                 missing = 0
                WHERE path = ?
            """, (timestamp, timestamp, str(project_path) if project_path else None, str(venv_path)))
            conn.commit()
        finally:
            conn.close()

    def track_activation(self, venv_path: Path, project_path: Optional[Path] = None):
        """Track an activation event for a venv"""
        venv_path = Path(venv_path).resolve()
        if not venv_path.exists():
            return

        if self.get(str(venv_path)) is None:
            self.register(venv_path, project_path=project_path)
            return

        self.update_last_used(venv_path, project_path=project_path)

    def mark_missing(self, venv_path: Path, is_missing: bool = True):
        """Mark a venv as missing or present"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE venvs SET missing = ? WHERE path = ?
            """, (1 if is_missing else 0, str(venv_path)))
            conn.commit()
        finally:
            conn.close()

    def refresh_metadata(self, venv_path: Path) -> bool:
        """Refresh size and package metadata for a venv"""
        venv_path = Path(venv_path).resolve()
        if not venv_path.exists():
            self.mark_missing(venv_path, True)
            return False

        size_bytes = get_directory_size(venv_path)
        size_mb = size_bytes / (1024 * 1024) if size_bytes else None
        package_count = self._count_packages(venv_path)
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()
        try:
            cursor.execute("""
                UPDATE venvs SET size_mb = ?,
                                 size_mb_cached_at = ?,
                                 package_count = ?,
                                 packages_cached_at = ?,
                                 missing = 0
                WHERE path = ?
            """, (size_mb, timestamp if size_mb is not None else None,
                  package_count, timestamp if package_count is not None else None,
                  str(venv_path)))
            conn.commit()
            return True
        finally:
            conn.close()

    def get(self, name_or_path: str) -> Optional[VenvRecord]:
        """Get venv by name or path"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            # Try by name first
            cursor.execute("SELECT * FROM venvs WHERE name = ?", (name_or_path,))
            row = cursor.fetchone()

            if not row:
                # Try by path
                cursor.execute("SELECT * FROM venvs WHERE path = ?", (name_or_path,))
                row = cursor.fetchone()

            if row:
                return VenvRecord(
                    name=row['name'],
                    path=row['path'],
                    project_path=row['project_path'],
                    python_version=row['python_version'],
                    created_at=row['created_at'],
                    last_used_at=row['last_used_at'],
                    last_seen_at=row['last_seen_at'],
                    size_mb=row['size_mb'],
                    size_mb_cached_at=row['size_mb_cached_at'],
                    package_count=row['package_count'],
                    packages_cached_at=row['packages_cached_at'],
                    activation_count=row['activation_count'],
                    missing=bool(row['missing']),
                    is_active=bool(row['is_active']),
                    notes=row['notes']
                )
            return None
        finally:
            conn.close()

    def list_all(self, sort_by: str = 'last_used_at') -> List[VenvRecord]:
        """
        List all registered venvs

        Args:
            sort_by: Field to sort by (name, last_used_at, size_mb, created_at)
        """
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            sort_map = {
                "name": ("name", "ASC"),
                "last_used_at": ("last_used_at", "DESC"),
                "size_mb": ("size_mb", "DESC"),
                "size": ("size_mb", "DESC"),
                "created_at": ("created_at", "DESC"),
                "project_path": ("project_path", "ASC"),
            }
            column, direction = sort_map.get(sort_by, sort_map["last_used_at"])
            cursor.execute(f"SELECT * FROM venvs ORDER BY {column} {direction}")
            rows = cursor.fetchall()

            return [
                VenvRecord(
                    name=row['name'],
                    path=row['path'],
                    project_path=row['project_path'],
                    python_version=row['python_version'],
                    created_at=row['created_at'],
                    last_used_at=row['last_used_at'],
                    last_seen_at=row['last_seen_at'],
                    size_mb=row['size_mb'],
                    size_mb_cached_at=row['size_mb_cached_at'],
                    package_count=row['package_count'],
                    packages_cached_at=row['packages_cached_at'],
                    activation_count=row['activation_count'],
                    missing=bool(row['missing']),
                    is_active=bool(row['is_active']),
                    notes=row['notes']
                )
                for row in rows
            ]
        finally:
            conn.close()

    def find_by_project(self, project_path: Path) -> Optional[VenvRecord]:
        """Find venv associated with a project"""
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT * FROM venvs WHERE project_path = ?", (str(project_path),))
            row = cursor.fetchone()

            if row:
                return VenvRecord(
                    name=row['name'],
                    path=row['path'],
                    project_path=row['project_path'],
                    python_version=row['python_version'],
                    created_at=row['created_at'],
                    last_used_at=row['last_used_at'],
                    last_seen_at=row['last_seen_at'],
                    size_mb=row['size_mb'],
                    size_mb_cached_at=row['size_mb_cached_at'],
                    package_count=row['package_count'],
                    packages_cached_at=row['packages_cached_at'],
                    activation_count=row['activation_count'],
                    missing=bool(row['missing']),
                    is_active=bool(row['is_active']),
                    notes=row['notes']
                )
            return None
        finally:
            conn.close()

    def cleanup_missing(self) -> int:
        """Remove registry entries for venvs that no longer exist"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT path FROM venvs")
            paths = [row[0] for row in cursor.fetchall()]

            removed = 0
            for path in paths:
                if not Path(path).exists():
                    cursor.execute("DELETE FROM venvs WHERE path = ?", (path,))
                    removed += 1

            conn.commit()
            return removed
        finally:
            conn.close()

    def get_stats(self) -> Dict:
        """Get statistics about registered venvs"""
        conn = sqlite3.connect(str(self.db_path))
        cursor = conn.cursor()

        try:
            cursor.execute("SELECT COUNT(*) FROM venvs")
            total = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM venvs WHERE COALESCE(missing, 0) = 1")
            missing_count = cursor.fetchone()[0]

            cursor.execute("""
                SELECT SUM(size_mb) FROM venvs
                WHERE size_mb IS NOT NULL AND COALESCE(missing, 0) = 0
            """)
            total_size = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT SUM(package_count) FROM venvs
                WHERE package_count IS NOT NULL AND COALESCE(missing, 0) = 0
            """)
            total_packages = cursor.fetchone()[0] or 0

            cursor.execute("""
                SELECT COUNT(*) FROM venvs
                WHERE COALESCE(missing, 0) = 0
                  AND last_used_at IS NOT NULL
                  AND datetime(replace(last_used_at, 'T', ' ')) < datetime('now', '-30 days')
            """)
            unused_30_days = cursor.fetchone()[0]

            cursor.execute("""
                SELECT COUNT(*) FROM venvs
                WHERE COALESCE(missing, 0) = 0
                  AND last_used_at IS NOT NULL
                  AND datetime(replace(last_used_at, 'T', ' ')) < datetime('now', '-90 days')
            """)
            unused_90_days = cursor.fetchone()[0]

            return {
                'total_venvs': total,
                'missing_venvs': missing_count,
                'total_size_mb': round(total_size, 2),
                'total_packages': total_packages,
                'unused_30_days': unused_30_days,
                'unused_90_days': unused_90_days
            }
        finally:
            conn.close()

    def _count_packages(self, venv_path: Path) -> Optional[int]:
        """Count packages in venv"""
        try:
            site_packages = venv_path / "Lib" / "site-packages"  # Windows
            if not site_packages.exists():
                # Try Unix path
                site_packages = venv_path / "lib"
                if site_packages.exists():
                    # Find python3.x directory
                    for item in site_packages.iterdir():
                        if item.is_dir() and item.name.startswith('python'):
                            site_packages = item / "site-packages"
                            break

            if site_packages.exists():
                # Count .dist-info directories (one per package)
                return len(list(site_packages.glob("*.dist-info")))
        except:
            pass
        return None

    def scan_and_register_all(self, search_paths: List[Path], max_depth: int = 3) -> int:
        """
        Scan filesystem and register found venvs
        This is the slow operation - only run on-demand
        """
        from venvy.performance import FastScanner

        scanner = FastScanner(max_depth=max_depth)
        registered = 0

        for search_path in search_paths:
            venv_paths = scanner.fast_discover_venvs(search_path, max_workers=2)

            for venv_path in venv_paths:
                # Try to detect project path (parent of venv)
                project_path = venv_path.parent

                if self.register(venv_path, project_path):
                    registered += 1

        return registered
