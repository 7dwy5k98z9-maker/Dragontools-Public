# -*- coding: utf-8 -*-
"""Projektstatistik und Kurzbeschreibung für den Über-Dialog.

Die Statistik wird im Entwicklungs-/Onedir-Build aus den vorhandenen
Python-Dateien berechnet. Falls ein Build keine Quellen mitliefert, bleiben
die zuletzt verifizierten Release-Werte als Fallback verfügbar.
"""
from __future__ import annotations

from dataclasses import dataclass
import ast
from pathlib import Path

from .resource_paths import BASE
from .version import APP_VERSION


@dataclass(frozen=True)
class ProjectStatistics:
    python_files: int
    total_lines: int
    code_lines: int
    test_package_files: int
    test_files: int
    static_tests: int
    dynamic: bool = False


# Wird bei Dokumentations-/Release-Pflege aktualisiert und dient nur als
# Fallback, wenn ein Frozen-Build keine .py-Quellen enthält.
RELEASE_STATISTICS = ProjectStatistics(
    python_files=986,
    total_lines=150125,
    code_lines=126908,
    test_package_files=233,
    test_files=229,
    static_tests=1736,
    dynamic=False,
)


def _source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    entry = root / "DragonToolsV9.py"
    if entry.is_file():
        files.append(entry)
    package = root / "dragontools"
    if package.is_dir():
        files.extend(
            p for p in package.rglob("*.py")
            if "__pycache__" not in p.parts
        )

    # Der eigenständige Dragon-HDR10+-Generator ist ein eigenes CLI/EXE,
    # gehört aber fachlich und statistisch zum DragonTools-Projekt. Gezählt
    # werden ausschließlich seine gepflegten Python-Quellen und Tests, nicht
    # etwaige lokale build-/dist-Artefakte.
    generator = root / "dragon_hdr10plus_generator"
    for relative in ("src", "tests"):
        folder = generator / relative
        if folder.is_dir():
            files.extend(
                p for p in folder.rglob("*.py")
                if "__pycache__" not in p.parts
            )
    return sorted(set(files))


def _count_static_tests(path: Path) -> int:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError, ValueError):
        return 0
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    )


def _fmt_int(value: int) -> str:
    return f"{value:,}".replace(",", ".")


def collect_project_statistics(root: str | Path | None = None) -> ProjectStatistics:
    base = Path(root) if root is not None else BASE
    files = _source_files(base)
    if not files:
        return RELEASE_STATISTICS

    total_lines = 0
    code_lines = 0
    for path in files:
        try:
            lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            continue
        total_lines += len(lines)
        code_lines += sum(
            1 for line in lines
            if line.strip() and not line.lstrip().startswith("#")
        )

    test_dirs = (
        base / "dragontools" / "tests",
        base / "dragon_hdr10plus_generator" / "tests",
    )
    package_test_files = sorted(
        p
        for tests_dir in test_dirs
        if tests_dir.is_dir()
        for p in tests_dir.glob("*.py")
    )
    test_files = [p for p in package_test_files if p.name.startswith("test_")]
    static_tests = sum(_count_static_tests(path) for path in test_files)

    return ProjectStatistics(
        python_files=len(files),
        total_lines=total_lines,
        code_lines=code_lines,
        test_package_files=len(package_test_files),
        test_files=len(test_files),
        static_tests=static_tests,
        dynamic=True,
    )


def build_about_html(root: str | Path | None = None) -> str:
    stats = collect_project_statistics(root)
    source_note = (
        "live aus dem Programmverzeichnis"
        if stats.dynamic
        else "verifizierte Release-Fallbackwerte"
    )
    return (
        f"<b>Dragon Tools V{APP_VERSION}</b><br>"
        "Modulares Medienwerkzeug für Konvertierung, Remux, Analyse und automatisierte Nachbearbeitung in einer PyQt6-Oberfläche.<br><br>"
        "<b>Video &amp; HDR</b><br>"
        "H.264 · H.265/HEVC · AV1 · NVENC · QSV · AMF · CPU/x265 · SVT-AV1<br>"
        "Dolby Vision · HDR10+ · HLG · SDR · RPU-Prüfung · Auto-Crop · IMAX · Downscale und optionales SDR→HDR-Enhancement<br><br>"
        "<b>Projektumfang (DragonTools + Dragon HDR10+ Generator)</b><br>"
        f"{_fmt_int(stats.python_files)} Python-Dateien/Programme · "
        f"{_fmt_int(stats.total_lines)} Gesamtzeilen · "
        f"{_fmt_int(stats.code_lines)} Codezeilen ({source_note})<br>"
        f"Tests: {stats.test_files} test_*.py · {_fmt_int(stats.static_tests)} statisch erkannte Tests<br><br>"
        "<b>Integrierte Zusatzkomponente</b><br>"
        "Dragon HDR10+ Generator (separate EXE/CLI, im Projektumfang enthalten)<br><br>"
        "<b>Externe Werkzeuge &amp; optionale Komponenten</b><br>"
        "FFmpeg/ffprobe · MKVToolNix/mkvmerge · MediaInfo · MakeMKV · dovi_tool · "
        "hdr10plus_tool · MP4Box · HandBrake · RMTS · Tesseract<br>"
        "Optional: ComfyUI · DaVinci Resolve · faster-whisper/CTranslate2 · lokale Whisper-Modelle · libvmaf · libplacebo"
    )
