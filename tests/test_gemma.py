"""Tests for Gemma integration (with mocked llama-cpp-python)."""
import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


class TestGemmaAvailability:
    def test_not_available_when_no_llama_cpp(self):
        import venvy.gemma as gemma_mod
        # Reset cached value
        gemma_mod._LLAMA_CPP_AVAILABLE = None

        with patch.dict("sys.modules", {"llama_cpp": None}):
            with patch("builtins.__import__", side_effect=ImportError):
                gemma_mod._LLAMA_CPP_AVAILABLE = None
                result = gemma_mod.is_gemma_available()
                # Should be False since import fails
                assert result is False

    def test_available_when_installed(self):
        import venvy.gemma as gemma_mod
        gemma_mod._LLAMA_CPP_AVAILABLE = None

        mock_module = MagicMock()
        with patch.dict("sys.modules", {"llama_cpp": mock_module}):
            gemma_mod._LLAMA_CPP_AVAILABLE = None
            gemma_mod._LLAMA_CPP_AVAILABLE = True  # Simulate successful import
            assert gemma_mod.is_gemma_available() is True


class TestGemmaAnalyzerFallback:
    def test_fallback_analyze_error_module_not_found(self):
        from venvy.gemma import GemmaAnalyzer
        analyzer = GemmaAnalyzer()

        result = analyzer._fallback_analyze_error(
            "ModuleNotFoundError: No module named 'pandas'",
            "Model not loaded"
        )

        assert "diagnosis" in result
        assert len(result["suggestions"]) > 0
        assert "pandas" in result["suggestions"][0]["command"]

    def test_fallback_analyze_error_permission(self):
        from venvy.gemma import GemmaAnalyzer
        analyzer = GemmaAnalyzer()

        result = analyzer._fallback_analyze_error(
            "PermissionError: [Errno 13] Permission denied",
            "Model not loaded"
        )

        assert len(result["suggestions"]) > 0
        assert any("permission" in s["action"].lower() for s in result["suggestions"])

    def test_fallback_analyze_error_dependency_conflict(self):
        from venvy.gemma import GemmaAnalyzer
        analyzer = GemmaAnalyzer()

        result = analyzer._fallback_analyze_error(
            "ERROR: pip's dependency resolver found conflicting requirements",
            "Model not loaded"
        )

        assert len(result["suggestions"]) > 0

    def test_fallback_analyze_error_unknown(self):
        from venvy.gemma import GemmaAnalyzer
        analyzer = GemmaAnalyzer()

        result = analyzer._fallback_analyze_error(
            "Some totally unknown error",
            "Model not loaded"
        )

        assert len(result["suggestions"]) > 0  # At least generic suggestion

    def test_fallback_smart_setup_with_requirements(self):
        from venvy.gemma import GemmaAnalyzer
        analyzer = GemmaAnalyzer()

        project_info = {
            "project_name": "myproject",
            "requirements_txt": ["requests>=2.0", "flask==3.0.0"],
            "files": ["requirements.txt"],
        }

        result = analyzer._fallback_smart_setup(project_info)

        assert result["packages"] == ["requests>=2.0", "flask==3.0.0"]
        assert result["python_version"] == "3.11"
        assert result["confidence"] > 0

    def test_fallback_smart_setup_empty(self):
        from venvy.gemma import GemmaAnalyzer
        analyzer = GemmaAnalyzer()

        result = analyzer._fallback_smart_setup({"project_name": "empty", "files": []})
        assert result["packages"] == []
        assert result["confidence"] <= 0.3


class TestProjectScanner:
    def test_scan_with_requirements(self, tmp_path):
        from venvy.gemma import GemmaAnalyzer
        analyzer = GemmaAnalyzer()

        (tmp_path / "requirements.txt").write_text("requests>=2.0\nflask\n# comment\n")

        info = analyzer._scan_project_files(tmp_path)
        assert "requirements.txt" in info["files"]
        assert "requests>=2.0" in info["requirements_txt"]
        assert "flask" in info["requirements_txt"]
        # Comments should be stripped
        assert not any(l.startswith("#") for l in info.get("requirements_txt", []))

    def test_scan_with_pyproject(self, tmp_path):
        from venvy.gemma import GemmaAnalyzer
        analyzer = GemmaAnalyzer()

        (tmp_path / "pyproject.toml").write_text(
            '[project]\nname = "test"\nrequires-python = ">=3.10"\n'
        )

        info = analyzer._scan_project_files(tmp_path)
        assert "pyproject.toml" in info["files"]

    def test_scan_empty_project(self, tmp_path):
        from venvy.gemma import GemmaAnalyzer
        analyzer = GemmaAnalyzer()

        info = analyzer._scan_project_files(tmp_path)
        assert info["files"] == []
