"""
Gemma 4 E2B integration for intelligent error analysis and project scanning.

Requires optional dependency: venvy[ai] (llama-cpp-python)
Falls back gracefully when llama-cpp-python is not installed.

The Gemma 4 E2B model (effective 2B active params, Q4_K_M quant ~3.5GB)
runs locally with ~5GB RAM, providing error diagnosis without external services.
"""
import json
import os
import sys
import urllib.request
from pathlib import Path
from typing import Optional, Dict, List

from venvy.utils import get_venvy_data_dir


# Lazy import check
_LLAMA_CPP_AVAILABLE = None


def is_gemma_available() -> bool:
    """Check if llama-cpp-python is installed."""
    global _LLAMA_CPP_AVAILABLE
    if _LLAMA_CPP_AVAILABLE is None:
        try:
            import llama_cpp  # noqa: F401
            _LLAMA_CPP_AVAILABLE = True
        except ImportError:
            _LLAMA_CPP_AVAILABLE = False
    return _LLAMA_CPP_AVAILABLE


class GemmaAnalyzer:
    """Error analysis and smart setup using Gemma 4 E2B via llama-cpp-python."""

    MODEL_FILENAME = "google_gemma-4-E2B-it-Q4_K_M.gguf"
    MODEL_REPO = "bartowski/google_gemma-4-E2B-it-GGUF"

    def __init__(self):
        self.model_dir = get_venvy_data_dir() / "models"
        self.model_path = self.model_dir / self.MODEL_FILENAME
        self._model = None

    def is_model_downloaded(self) -> bool:
        """Check if the model file exists locally."""
        return self.model_path.exists()

    def download_model(self, progress_callback=None) -> bool:
        """
        Download the Gemma 4 E2B GGUF model from Hugging Face.

        Returns True if download succeeds or model already exists.
        """
        if self.is_model_downloaded():
            return True

        self.model_dir.mkdir(parents=True, exist_ok=True)

        url = f"https://huggingface.co/{self.MODEL_REPO}/resolve/main/{self.MODEL_FILENAME}"

        try:
            def _reporthook(block_num, block_size, total_size):
                if progress_callback and total_size > 0:
                    progress_callback(block_num * block_size, total_size)

            urllib.request.urlretrieve(url, str(self.model_path), _reporthook)
            return True
        except Exception:
            # Clean up partial download
            if self.model_path.exists():
                self.model_path.unlink()
            return False

    def _load_model(self):
        """Lazy-load the model into memory."""
        if self._model is None:
            if not is_gemma_available():
                raise ImportError("llama-cpp-python not installed. Run: pip install venvy[ai]")
            if not self.is_model_downloaded():
                raise FileNotFoundError(f"Model not found at {self.model_path}. Run download first.")

            from llama_cpp import Llama

            self._model = Llama(
                model_path=str(self.model_path),
                n_ctx=4096,
                n_threads=min(4, os.cpu_count() or 2),
                verbose=False,
            )

    def analyze_error(self, error_text: str, context: Optional[str] = None) -> Dict:
        """
        Analyze pip/build error output and suggest fixes.

        Returns:
            {
                "diagnosis": str,
                "root_cause": str,
                "suggestions": [
                    {"action": str, "command": str, "confidence": float}
                ],
            }
        """
        try:
            self._load_model()
        except (ImportError, FileNotFoundError) as e:
            return self._fallback_analyze_error(error_text, str(e))

        prompt = self._build_error_prompt(error_text, context)
        response = self._generate(prompt, max_tokens=1024)

        return self._parse_error_response(response, error_text)

    def smart_setup(self, project_path: Path) -> Dict:
        """
        Scan project files and suggest environment configuration.

        Examines: requirements.txt, pyproject.toml, setup.py, Pipfile,
                  import statements in .py files.

        Returns:
            {
                "python_version": str,
                "packages": List[str],
                "dev_packages": List[str],
                "suggested_name": str,
                "confidence": float,
            }
        """
        # Gather project info
        project_info = self._scan_project_files(project_path)

        try:
            self._load_model()
        except (ImportError, FileNotFoundError):
            return self._fallback_smart_setup(project_info)

        prompt = self._build_setup_prompt(project_info)
        response = self._generate(prompt, max_tokens=1024)

        return self._parse_setup_response(response, project_info)

    def analyze_event(self, event_data: Dict) -> Dict:
        """
        Analyze a pip event for bloat, unused packages, or optimization.

        Called on-demand by PipObserver when alert thresholds are crossed.

        Returns:
            {
                "assessment": str,
                "details": str,
                "recommendations": List[str],
                "severity": str,  # "info" / "warn" / "critical"
            }
        """
        try:
            self._load_model()
        except (ImportError, FileNotFoundError):
            return self._fallback_analyze_event(event_data)

        prompt = self._build_event_prompt(event_data)
        response = self._generate(prompt, max_tokens=512)

        return self._parse_event_response(response, event_data)

    def _generate(self, prompt: str, max_tokens: int = 1024) -> str:
        """Run inference on the loaded model."""
        if self._model is None:
            return ""

        result = self._model(
            prompt,
            max_tokens=max_tokens,
            temperature=0.1,
            stop=["```", "\n\n\n"],
        )

        return result["choices"][0]["text"] if result.get("choices") else ""

    # ========================================================================
    # PROMPT BUILDERS
    # ========================================================================

    def _build_error_prompt(self, error_text: str, context: Optional[str] = None) -> str:
        """Build prompt for error analysis."""
        truncated = error_text[:3000]  # Keep within context window

        prompt = f"""Analyze this Python pip/build error and provide a fix.

Error:
{truncated}

Respond in this exact JSON format:
{{"diagnosis": "one sentence summary", "root_cause": "specific cause", "suggestions": [{{"action": "what to do", "command": "exact command to run", "confidence": 0.9}}]}}

JSON response:"""

        return prompt

    def _build_setup_prompt(self, project_info: Dict) -> str:
        """Build prompt for smart setup analysis."""
        prompt = f"""Analyze this Python project and suggest environment configuration.

Project info:
{json.dumps(project_info, indent=2)}

Respond in this exact JSON format:
{{"python_version": "3.11", "packages": ["pkg1", "pkg2"], "dev_packages": ["pytest"], "suggested_name": "project-env", "confidence": 0.8}}

JSON response:"""

        return prompt

    def _build_event_prompt(self, event_data: Dict) -> str:
        """Build prompt for pip event analysis."""
        prompt = f"""Analyze this pip event and assess whether it indicates bloat or issues.

Event:
- Action: {event_data.get('action', 'install')}
- Packages added: {event_data.get('packages_added', [])}
- Packages removed: {event_data.get('packages_removed', [])}
- Size delta: {event_data.get('size_delta_mb', 'unknown')} MB
- Total env size: {event_data.get('total_env_size_mb', 'unknown')} MB
- Exit code: {event_data.get('exit_code', 0)}

Respond in this exact JSON format:
{{"assessment": "one sentence", "details": "explanation", "recommendations": ["action1", "action2"], "severity": "info"}}

JSON response:"""
        return prompt

    # ========================================================================
    # RESPONSE PARSERS
    # ========================================================================

    def _parse_error_response(self, response: str, error_text: str) -> Dict:
        """Parse model response for error analysis."""
        try:
            # Try to find JSON in the response
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                return json.loads(response[start:end])
        except (json.JSONDecodeError, ValueError):
            pass

        # Return raw response as diagnosis
        return {
            "diagnosis": response.strip() or "Unable to analyze error",
            "root_cause": "See diagnosis",
            "suggestions": [],
        }

    def _parse_setup_response(self, response: str, project_info: Dict) -> Dict:
        """Parse model response for smart setup."""
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(response[start:end])
                # Ensure required fields
                result.setdefault("python_version", "3.11")
                result.setdefault("packages", [])
                result.setdefault("dev_packages", [])
                result.setdefault("suggested_name", ".venv")
                result.setdefault("confidence", 0.5)
                return result
        except (json.JSONDecodeError, ValueError):
            pass

        return self._fallback_smart_setup(project_info)

    def _parse_event_response(self, response: str, event_data: Dict) -> Dict:
        """Parse model response for event analysis."""
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(response[start:end])
                result.setdefault("assessment", "Unknown")
                result.setdefault("details", "")
                result.setdefault("recommendations", [])
                result.setdefault("severity", "info")
                return result
        except (json.JSONDecodeError, ValueError):
            pass

        return self._fallback_analyze_event(event_data)

    # ========================================================================
    # FALLBACKS (when model is not available)
    # ========================================================================

    def _fallback_analyze_error(self, error_text: str, load_error: str) -> Dict:
        """Rule-based error analysis when Gemma is not available."""
        error_lower = error_text.lower()
        suggestions = []

        if "modulenotfounderror" in error_lower or "no module named" in error_lower:
            # Extract module name
            for line in error_text.splitlines():
                if "no module named" in line.lower():
                    parts = line.split("'")
                    if len(parts) >= 2:
                        module = parts[1].split(".")[0]
                        suggestions.append({
                            "action": f"Install missing module '{module}'",
                            "command": f"venvy safe-install {module}",
                            "confidence": 0.9,
                        })
                    break

        elif "could not find a version" in error_lower:
            suggestions.append({
                "action": "Check package name spelling and available versions",
                "command": "pip index versions <package-name>",
                "confidence": 0.7,
            })

        elif "error: microsoft visual c++" in error_lower or "cl.exe" in error_lower:
            suggestions.append({
                "action": "Install Visual C++ Build Tools",
                "command": "winget install Microsoft.VisualStudio.2022.BuildTools",
                "confidence": 0.8,
            })

        elif "permission" in error_lower or "access is denied" in error_lower:
            suggestions.append({
                "action": "Run with elevated permissions or use a virtual environment",
                "command": "venvy ensure",
                "confidence": 0.8,
            })

        elif "conflicting" in error_lower or "incompatible" in error_lower:
            suggestions.append({
                "action": "Resolve dependency conflict by creating a fresh environment",
                "command": "venvy rollback --latest",
                "confidence": 0.7,
            })

        if not suggestions:
            suggestions.append({
                "action": "Review the error output and try installing dependencies one by one",
                "command": "venvy safe-install <package>",
                "confidence": 0.3,
            })

        return {
            "diagnosis": "Rule-based analysis (Gemma AI not loaded)",
            "root_cause": load_error,
            "suggestions": suggestions,
            "_note": "Install venvy[ai] for AI-powered analysis",
        }

    def _fallback_smart_setup(self, project_info: Dict) -> Dict:
        """Rule-based project analysis when Gemma is not available."""
        packages = []
        dev_packages = []

        # Extract from requirements.txt
        if project_info.get("requirements_txt"):
            for line in project_info["requirements_txt"]:
                line = line.strip()
                if line and not line.startswith("#"):
                    packages.append(line)

        # Extract from pyproject.toml dependencies
        if project_info.get("pyproject_dependencies"):
            packages.extend(project_info["pyproject_dependencies"])

        if project_info.get("pyproject_dev_dependencies"):
            dev_packages.extend(project_info["pyproject_dev_dependencies"])

        python_version = project_info.get("python_requires") or "3.11"

        return {
            "python_version": python_version,
            "packages": packages,
            "dev_packages": dev_packages,
            "suggested_name": project_info.get("project_name", ".venv"),
            "confidence": 0.6 if packages else 0.3,
        }

    def _fallback_analyze_event(self, event_data: Dict) -> Dict:
        """Rule-based event analysis when Gemma is not available."""
        recommendations = []
        severity = "info"
        assessment = "Normal operation"
        details = ""

        size_delta = event_data.get("size_delta_mb") or 0
        packages_added = event_data.get("packages_added", [])
        total_size = event_data.get("total_env_size_mb") or 0
        exit_code = event_data.get("exit_code", 0)

        if exit_code != 0:
            severity = "warn"
            assessment = "Install failed"
            details = f"pip exited with code {exit_code}"
            recommendations.append("Check error output and try venvy analyze-error")

        elif size_delta > 500:
            severity = "warn"
            assessment = "Large install detected"
            details = f"Estimated +{size_delta:.0f}MB from this install"
            recommendations.append("Review if all transitive dependencies are needed")
            recommendations.append("Consider venvy checkpoint before further changes")

        elif len(packages_added) > 20:
            severity = "warn"
            assessment = "Many new dependencies"
            details = f"{len(packages_added)} packages added in one install"
            recommendations.append("Consider pinning versions to avoid future bloat")

        elif total_size > 2000:
            severity = "info"
            assessment = "Large environment"
            details = f"Environment is {total_size:.0f}MB"
            recommendations.append("Run venvy doctor to check for cleanup opportunities")

        return {
            "assessment": assessment,
            "details": details,
            "recommendations": recommendations,
            "severity": severity,
        }

    # ========================================================================
    # PROJECT SCANNER
    # ========================================================================

    def _scan_project_files(self, project_path: Path) -> Dict:
        """Scan project directory for configuration files."""
        info = {
            "project_name": project_path.name,
            "files": [],
        }

        # Check for requirements.txt
        req_file = project_path / "requirements.txt"
        if req_file.exists():
            try:
                lines = req_file.read_text(encoding="utf-8", errors="ignore").splitlines()
                info["requirements_txt"] = [l.strip() for l in lines if l.strip() and not l.startswith("#")]
                info["files"].append("requirements.txt")
            except OSError:
                pass

        # Check for pyproject.toml
        pyproject = project_path / "pyproject.toml"
        if pyproject.exists():
            info["files"].append("pyproject.toml")
            try:
                content = pyproject.read_text(encoding="utf-8", errors="ignore")
                info["pyproject_content_preview"] = content[:2000]
                # Basic parsing for dependencies
                deps = []
                dev_deps = []
                in_deps = False
                in_dev_deps = False
                for line in content.splitlines():
                    stripped = line.strip()
                    if stripped.startswith("dependencies"):
                        in_deps = True
                        in_dev_deps = False
                    elif stripped.startswith("dev") and "dependencies" in stripped:
                        in_dev_deps = True
                        in_deps = False
                    elif stripped.startswith("[") and not stripped.startswith('["'):
                        in_deps = False
                        in_dev_deps = False
                    elif (in_deps or in_dev_deps) and stripped.startswith('"'):
                        dep = stripped.strip('",').strip()
                        if dep:
                            if in_dev_deps:
                                dev_deps.append(dep)
                            else:
                                deps.append(dep)
                    if "requires-python" in stripped:
                        # Extract python version
                        parts = stripped.split("=")
                        if len(parts) >= 2:
                            ver = parts[-1].strip().strip('"').strip(">=").strip()
                            info["python_requires"] = ver

                info["pyproject_dependencies"] = deps
                info["pyproject_dev_dependencies"] = dev_deps
            except OSError:
                pass

        # Check for setup.py
        setup_py = project_path / "setup.py"
        if setup_py.exists():
            info["files"].append("setup.py")

        # Check for Pipfile
        pipfile = project_path / "Pipfile"
        if pipfile.exists():
            info["files"].append("Pipfile")

        # Check for .python-version
        python_version_file = project_path / ".python-version"
        if python_version_file.exists():
            try:
                info["python_version_file"] = python_version_file.read_text().strip()
                info["files"].append(".python-version")
            except OSError:
                pass

        return info
