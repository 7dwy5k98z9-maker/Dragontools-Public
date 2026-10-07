# -*- coding: utf-8 -*-
from __future__ import annotations

import importlib
import re
from pathlib import Path

from .release_validation_common import ReleaseCheck

def _requirement_names(path: Path, *, _seen: set[Path] | None = None) -> set[str]:
    """Liest Paketnamen rekursiv aus pip-Requirements inklusive ``-r``."""
    path = path.resolve()
    if not path.is_file():
        return set()
    seen = _seen if _seen is not None else set()
    if path in seen:
        return set()
    seen.add(path)

    names: set[str] = set()
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        include = re.match(r"^-r\s*([^\s]+)$", line, flags=re.IGNORECASE)
        if include:
            names.update(_requirement_names(path.parent / include.group(1), _seen=seen))
            continue
        if line.startswith("-"):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)", line)
        if match:
            names.add(match.group(1).casefold().replace("_", "-"))
    return names


def _requirement_specs(path: Path, *, _seen: set[Path] | None = None) -> dict[str, str]:
    """Return normalized package -> specifier text, following ``-r`` includes."""
    path = path.resolve()
    if not path.is_file():
        return {}
    seen = _seen if _seen is not None else set()
    if path in seen:
        return {}
    seen.add(path)
    specs: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = raw_line.split("#", 1)[0].strip()
        if not line:
            continue
        include = re.match(r"^-r\s*([^\s]+)$", line, flags=re.IGNORECASE)
        if include:
            specs.update(_requirement_specs(path.parent / include.group(1), _seen=seen))
            continue
        if line.startswith("-"):
            continue
        match = re.match(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]+\])?\s*(.*)$", line)
        if not match:
            continue
        name = match.group(1).casefold().replace("_", "-")
        spec = match.group(2).split(";", 1)[0].strip().replace(" ", "")
        specs[name] = spec
    return specs


def _has_reproducible_bound(spec: str) -> bool:
    from .release_requirement_bounds import has_reproducible_bound
    return has_reproducible_bound(spec)


def _unbounded_requirements(path: Path, names: set[str]) -> list[str]:
    specs = _requirement_specs(path)
    return sorted(name for name in names if name in specs and not _has_reproducible_bound(specs[name]))


def _check_runtime_environment(root: Path) -> ReleaseCheck:
    requirements = root / "requirements-runtime.txt"
    if not requirements.is_file():
        return ReleaseCheck(
            "error",
            "Runtime-Abhängigkeiten",
            "requirements-runtime.txt fehlt; das Quellpaket ist nicht reproduzierbar installierbar.",
        )
    declared = _requirement_names(requirements)
    required = {"pyqt6", "cryptography", "defusedxml", "packaging"}
    missing = sorted(required - declared)
    if missing:
        return ReleaseCheck(
            "error",
            "Runtime-Abhängigkeiten",
            "requirements-runtime.txt deklariert nicht: " + ", ".join(missing),
        )
    unbounded = _unbounded_requirements(requirements, required)
    if unbounded:
        return ReleaseCheck(
            "error",
            "Runtime-Abhängigkeiten",
            "Fehlende reproduzierbare Versionsgrenzen: " + ", ".join(unbounded),
        )
    return ReleaseCheck(
        "ok",
        "Runtime-Abhängigkeiten",
        "PyQt6, cryptography und defusedxml sind als zwingende Runtime-Abhängigkeiten deklariert.",
    )


def _check_optional_environment(root: Path) -> ReleaseCheck:
    requirements = root / "requirements-optional.txt"
    if not requirements.is_file():
        return ReleaseCheck(
            "warn",
            "Optionale Abhängigkeiten",
            "requirements-optional.txt fehlt; optionale Bildanalyse-/Whisper-Abhängigkeiten sind nicht dokumentiert.",
        )
    declared = _requirement_names(requirements)
    expected = {"numpy", "opencv-python-headless", "faster-whisper", "ctranslate2"}
    missing = sorted(expected - declared)
    if missing:
        return ReleaseCheck(
            "warn",
            "Optionale Abhängigkeiten",
            "Nicht vollständig deklariert: " + ", ".join(missing),
        )
    unbounded = _unbounded_requirements(requirements, expected)
    if unbounded:
        return ReleaseCheck(
            "warn",
            "Optionale Abhängigkeiten",
            "Optionale Pakete ohne reproduzierbare Versionsgrenzen: " + ", ".join(unbounded),
        )
    return ReleaseCheck(
        "ok",
        "Optionale Abhängigkeiten",
        "NumPy/OpenCV sowie faster-whisper/CTranslate2 sind als optionale Laufzeit-/Build-Abhängigkeiten dokumentiert.",
    )


def _check_build_environment(root: Path) -> ReleaseCheck:
    """Prueft die reproduzierbare PyInstaller-Buildumgebung."""
    runtime_requirements = root / "requirements-runtime.txt"
    optional_requirements = root / "requirements-optional.txt"
    whisper_requirements = root / "requirements-whisper.txt"
    requirements = root / "requirements-build.txt"
    build_script = root / "build_v9.bat"
    missing_files = [
        path.name
        for path in (runtime_requirements, optional_requirements, whisper_requirements, requirements, build_script)
        if not path.is_file()
    ]
    if missing_files:
        return ReleaseCheck(
            "error",
            "Build-Umgebung",
            "Fehlende Build-Dateien: " + ", ".join(missing_files),
        )

    declared = _requirement_names(requirements)
    missing_packages = [
        name for name in ("pyinstaller", "pyinstaller-hooks-contrib", "pypdf")
        if name not in declared
    ]
    if missing_packages:
        return ReleaseCheck(
            "error",
            "Build-Umgebung",
            "requirements-build.txt deklariert nicht: " + ", ".join(missing_packages),
        )
    unbounded_build = _unbounded_requirements(requirements, set(declared))
    if unbounded_build:
        return ReleaseCheck(
            "error",
            "Build-Umgebung",
            "Build-Abhängigkeiten ohne reproduzierbare Versionsgrenzen: " + ", ".join(unbounded_build),
        )

    req_text = requirements.read_text(encoding="utf-8", errors="replace").casefold().replace(" ", "")
    missing_includes = [
        name
        for name in ("requirements-runtime.txt", "requirements-optional.txt")
        if f"-r{name}" not in req_text
    ]
    if missing_includes:
        return ReleaseCheck(
            "error",
            "Build-Umgebung",
            "requirements-build.txt bindet nicht ein: " + ", ".join(missing_includes),
        )

    build_text = build_script.read_text(encoding="utf-8", errors="replace").casefold()
    required_build_tokens = (
        "defusedxml",
        "faster_whisper",
        "ctranslate2",
        "requirements-whisper.txt",
        "pip install -r requirements-whisper.txt",
        "from importlib.metadata import version",
        "--collect-submodules faster_whisper",
        "--collect-binaries faster_whisper",
        "--collect-data faster_whisper",
        "--collect-submodules ctranslate2",
        "--collect-binaries ctranslate2",
        "--collect-data ctranslate2",
        "--copy-metadata faster-whisper",
        "--smoke-test",
        "waitforexit(90000)",
        "finalen frozen-runtime-smoke",
    )
    missing_tokens = [token for token in required_build_tokens if token not in build_text]
    if missing_tokens:
        return ReleaseCheck(
            "error",
            "Build-Umgebung",
            "build_v9.bat bildet den Runtime-/Whisper-Vertrag nicht vollstaendig ab: "
            + ", ".join(missing_tokens),
        )

    optional_declared = _requirement_names(optional_requirements)
    whisper_declared = _requirement_names(whisper_requirements)
    missing_whisper = sorted({"faster-whisper", "ctranslate2"} - whisper_declared)
    if missing_whisper:
        return ReleaseCheck(
            "error",
            "Build-Umgebung",
            "requirements-whisper.txt deklariert die fuer den offiziellen EXE-Build benoetigten Whisper-Pakete nicht: "
            + ", ".join(missing_whisper),
        )
    if not {"faster-whisper", "ctranslate2"} <= optional_declared:
        return ReleaseCheck(
            "error",
            "Build-Umgebung",
            "requirements-optional.txt bindet requirements-whisper.txt nicht wirksam ein.",
        )

    whisper_text = whisper_requirements.read_text(encoding="utf-8", errors="replace").casefold().replace(" ", "")
    expected_constraints = ("faster-whisper>=1.1,<2", "ctranslate2>=4.4,<5")
    missing_constraints = [item for item in expected_constraints if item not in whisper_text]
    if missing_constraints:
        return ReleaseCheck(
            "error",
            "Build-Umgebung",
            "Whisper-Versionsgrenzen fehlen/abweichend: " + ", ".join(missing_constraints),
        )

    return ReleaseCheck(
        "ok",
        "Build-Umgebung",
        "PyInstaller, Hooks und Runtime-/OpenCV-Abhaengigkeiten sind deklariert; Whisper/CTranslate2 besitzen getrennte Versionsgrenzen, werden vor dem Build validiert/repariert und von PyInstaller gesammelt.",
    )


def _check_test_environment(root: Path) -> ReleaseCheck:
    """Prueft die deklarierte Pytest-/Qt-Testumgebung des Quellprojekts."""
    runtime_requirements = root / "requirements-runtime.txt"
    requirements = root / "requirements-test.txt"
    pytest_ini = root / "pytest.ini"
    missing_files = [
        str(path.name)
        for path in (runtime_requirements, requirements, pytest_ini)
        if not path.is_file()
    ]
    if missing_files:
        return ReleaseCheck(
            "error",
            "Testumgebung",
            "Fehlende Testdateien: " + ", ".join(missing_files),
        )

    test_names = _requirement_names(requirements)
    runtime_names = _requirement_names(runtime_requirements)
    missing_packages: list[str] = []
    for name in ("pytest", "pytest-qt"):
        if name not in test_names:
            missing_packages.append(name)
    if "pyqt6" not in runtime_names:
        missing_packages.append("PyQt6 (runtime)")
    if missing_packages:
        return ReleaseCheck(
            "error",
            "Testumgebung",
            "Test-/Runtime-Requirements deklarieren nicht: " + ", ".join(missing_packages),
        )
    req_text = requirements.read_text(encoding="utf-8", errors="replace").casefold().replace(" ", "")
    if "-rrequirements-runtime.txt" not in req_text:
        return ReleaseCheck(
            "error",
            "Testumgebung",
            "requirements-test.txt bindet requirements-runtime.txt nicht ein.",
        )
    if "pypdf" not in test_names:
        return ReleaseCheck(
            "error",
            "Testumgebung",
            "requirements-test.txt deklariert pypdf für die PDF-Privacy-Regressionstests nicht.",
        )

    unbounded_tests = _unbounded_requirements(requirements, {"pytest", "pytest-qt", "pypdf"})
    if unbounded_tests:
        return ReleaseCheck(
            "error",
            "Testumgebung",
            "Test-Abhängigkeiten ohne reproduzierbare Versionsgrenzen: " + ", ".join(unbounded_tests),
        )

    ini_text = pytest_ini.read_text(encoding="utf-8", errors="replace").casefold().replace(" ", "")
    if "qt_api=pyqt6" not in ini_text:
        return ReleaseCheck(
            "warn",
            "Testumgebung",
            "pytest.ini legt PyQt6 nicht explizit als qt_api fest.",
        )
    if (root / "dragon_hdr10plus_generator").exists() and "dragon_hdr10plus_generator/tests" not in ini_text:
        return ReleaseCheck(
            "error",
            "Testumgebung",
            "pytest.ini bindet die vorhandene Standalone-HDR10+-Generator-Suite nicht in den Standardlauf ein.",
        )
    missing_markers = [
        marker
        for marker in ("media_integration", "dv_hdr_integration")
        if f"{marker}:" not in ini_text
    ]
    if missing_markers:
        return ReleaseCheck(
            "warn",
            "Testumgebung",
            "pytest.ini registriert nicht: " + ", ".join(missing_markers),
        )
    return ReleaseCheck(
        "ok",
        "Testumgebung",
        "Runtime-Abhängigkeiten, pytest, pytest-qt, PyQt6, die Standalone-Generator-Suite sowie Media-/DV-HDR-Integrationstest-Marker sind reproduzierbar deklariert.",
    )


def _check_ci_workflow(root: Path) -> ReleaseCheck:
    workflow = root / ".github" / "workflows" / "tests.yml"
    if not workflow.is_file():
        return ReleaseCheck("error", "CI-Workflow", f"Nicht gefunden: {workflow}")
    text = workflow.read_text(encoding="utf-8", errors="replace")
    required_tokens = (
        "DRAGONTOOLS_REQUIRE_QT_TESTS",
        "QT_QPA_PLATFORM",
        "requirements-test.txt",
        "cache-dependency-path:",
        "requirements-runtime.txt",
        "requirements-optional.txt",
        "not dv_hdr_integration",
        "ruff check",
        "--select E9,F821,F822,F823",
        "DRAGONTOOLS_REQUIRE_DV_HDR_INTEGRATION",
        "self-hosted",
        "dragontools-media",
        "pyinstaller-smoke",
        "DragonToolsSmoke.exe",
        "--smoke-test",
        "hdrtvdm-bridge",
        "test_patch_ai_hdrtvdm_bridge_optional.py",
        "refs/tags/v",
    )
    missing = [token for token in required_tokens if token not in text]
    if missing:
        return ReleaseCheck(
            "error",
            "CI-Workflow",
            "CI erzwingt die vollständige Qt-Testumgebung nicht: " + ", ".join(missing),
        )
    return ReleaseCheck(
        "ok",
        "CI-Workflow",
        "Linux-/Windows-CI erzwingt Qt und Ruff-F821/E9; zusätzlich laufen ein echter PyInstaller-Haupt-EXE-Smoke und HDRTVDM-CPU-Lifecycle-Test. Reale DV/HDR-Roundtrips sind bei Release-Tags bzw. manuell ein striktes self-hosted Gate.",
    )


def _check_dv_hdr_integration_contract(root: Path) -> ReleaseCheck:
    test_file = root / "dragontools" / "tests" / "test_real_dv_hdr_integration.py"
    guide = root / "INTEGRATION_TESTS.md"
    missing = [path.name for path in (test_file, guide) if not path.is_file()]
    if missing:
        return ReleaseCheck(
            "error",
            "DV/HDR-Integrationstests",
            "Fehlende Integrationsartefakte: " + ", ".join(missing),
        )
    test_text = test_file.read_text(encoding="utf-8", errors="replace")
    required_tokens = (
        "DVRpuService",
        "DVMP4BoxMuxer",
        "HDR10PlusBitstreamService",
        "dv_hdr_integration",
    )
    missing_tokens = [token for token in required_tokens if token not in test_text]
    if missing_tokens:
        return ReleaseCheck(
            "error",
            "DV/HDR-Integrationstests",
            "Integrationssuite deckt nicht alle verlangten realen Pfade ab: " + ", ".join(missing_tokens),
        )
    return ReleaseCheck(
        "ok",
        "DV/HDR-Integrationstests",
        "Realer DV-RPU/MP4Box- und HDR10+-Extract/Inject/Verify-Roundtrip ist als separate Testklasse vorhanden.",
    )

def _check_opencv_dependency() -> ReleaseCheck:
    try:
        cv2 = importlib.import_module("cv2")
        version = str(getattr(cv2, "__version__", "") or "").strip()
        detail = f"Verfügbar{f' ({version})' if version else ''}: Audio-Video-Matcher nutzt OpenCV für robuste Bildvergleiche."
        return ReleaseCheck("ok", "OpenCV-Bildanalyse", detail)
    except Exception as exc:
        return ReleaseCheck(
            "warn",
            "OpenCV-Bildanalyse",
            "Nicht verfügbar: Audio-Video-Matcher nutzt den FFmpeg/dHash-Fallback. "
            f"Für bessere Trefferquote opencv-python-headless installieren. ({exc})",
        )
