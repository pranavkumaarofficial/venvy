import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from venvy.registry import VenvRegistry
from venvy.models import EnvironmentInfo, EnvironmentType, HealthStatus
from venvy.analysis import EnvironmentAnalysis


ROOT = Path(__file__).parent


def _registry_records():
    registry = VenvRegistry()
    records = registry.list_all()
    return records, registry.get_stats()


def _suggestions_from_registry(records):
    analysis = EnvironmentAnalysis()
    environments = []

    for record in records:
        size_bytes = int(record.size_mb * 1024 * 1024) if record.size_mb else None
        days_since_used = None
        if record.last_used_at:
            try:
                from datetime import datetime
                dt = datetime.fromisoformat(record.last_used_at.replace("T", " "))
                days_since_used = (datetime.now() - dt).days
            except Exception:
                pass

        env = EnvironmentInfo(
            name=record.name,
            path=Path(record.path),
            type=EnvironmentType.UNKNOWN,
            python_version=record.python_version,
            size_bytes=size_bytes,
            package_count=record.package_count,
            health_status=HealthStatus.UNKNOWN,
            activation_count=record.activation_count,
            days_since_used=days_since_used,
            linked_projects=[Path(record.project_path)] if record.project_path else None,
            is_orphaned=record.project_path is None,
        )
        environments.append(env)

    suggestions = analysis.generate_cleanup_suggestions(environments)
    return [
        {
            "name": s.environment.name,
            "reason": s.reason,
            "confidence": s.confidence,
            "risk_level": s.risk_level,
            "space_recovered": s.space_recovered,
        }
        for s in suggestions
    ]


class Handler(SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path = urlparse(path).path
        full = (ROOT / path.lstrip("/")).resolve()
        if full.is_dir():
            return str(full / "index.html")
        return str(full)

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/api/registry":
            records, stats = _registry_records()
            payload = {
                "stats": stats,
                "records": [
                    {
                        **r.to_dict(),
                        "health_status": "broken" if r.missing else "unknown",
                    }
                    for r in records
                ],
            }
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        if parsed.path == "/api/suggestions":
            records, _ = _registry_records()
            payload = {"suggestions": _suggestions_from_registry(records)}
            body = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        return super().do_GET()


def main():
    import sys
    port = 5173
    if len(sys.argv) > 1:
        try:
            port = int(sys.argv[1])
        except ValueError:
            pass
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"UI running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
