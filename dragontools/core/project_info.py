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

from .paths import BASE
from .settings import APP_VERSION


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
    python_files=729,
    total_lines=118227,
    code_lines=100301,
    test_package_files=167,
    test_files=164,
    static_tests=1224,
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

    tests_dir = base / "dragontools" / "tests"
    package_test_files = sorted(tests_dir.glob("*.py")) if tests_dir.is_dir() else []
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
    source_note = "live aus dem Programmverzeichnis" if stats.dynamic else "verifizierte Release-Fallbackwerte"
    return (
        f"<b>Dragon Tools V{APP_VERSION}</b><br>"
        "Dragon Tools ist ein modulares Medienwerkzeug für Konvertierung, Remux, Analyse, Metadaten, Mediathek, Validierung, Reparatur und Nachbearbeitung in einer PyQt6-Oberfläche.<br><br>"
        "<b>Video &amp; HDR</b><br>"
        "H.264 · H.265/HEVC · AV1 · NVENC · QSV · AMF · CPU/x265 · SVT-AV1<br>"
        "DV- und HDR10+-Erhalt · Dolby-Vision-RPU-Prüfung · Auto-Crop · IMAX · Downscale-only<br>"
        "Der HDR10+-Workflow nutzt den direkten 5-Schritt-Pfad; MP4Box und mkvmerge/mkvextract sichern die jeweiligen MP4-/MKV-Spezialpfade ab.<br><br>"
        "<b>Workflow &amp; Sicherheit</b><br>"
        "Per-Datei-Overrides · Audio-/Untertitelregeln · Sidecars · ISO/BDMV · Remux · Merge · Audio-Mux<br>"
        "Audio-Video-Matcher · Qualitätstester · Timestamp-Reparatur mit +genpts/+igndts-Fallback · transaktionaler Output-Commit · Move-Recovery<br>"
        "Qt-sicheres Async-Postprocessing · exactly-once NFO/Trickplay-Scheduling · transaktionaler Trickplay-Commit<br>"
        "Move-Journal-Archivierung fail-closed · Journal-Finalisierung zählt als Move-Fehler statt als sauberer Abschluss<br><br>"
        "<b>Metadaten &amp; Mediathek</b><br>"
        "TMDB · TheTVDB · Renamer-Regeln · mehrstufiges Fuzzy-Matching · Jellyfin-NFO · Trickplay<br>"
        "SQLite-Mediathek Schema 6 · Jellyfin-Import · indexierter Serien-Lookup · asynchrone Suche · NFO-Lightscan<br>"
        "DB-first Preflight · frische Batch-Metadaten für finale Rename-/NFO-Läufe · TheTVDB-Sprachfallback<br>"
        "Generische Episodentitel wie Folge XX werden bei Bedarf frisch geprüft statt dauerhaft aus dem Cache übernommen.<br><br>"
        "<b>Architektur</b><br>"
        "Zwölf Refactoring-/Stabilitätsblöcke trennen große GUI-, Core- und Worker-Abläufe in fokussierte Fachmodule.<br>"
        "Schmale Fassaden halten bestehende Importpfade stabil; der Release-Smoke deckt alle im Review-Manifest neu eingeführten Produktivmodule ab.<br>"
        "Die Quellbildprüfung bündelt mehrere Probezeitpunkte pro FFmpeg-Prozess und reduziert damit Prozessstarts deutlich.<br><br>"
        f"<b>Projektumfang ({source_note})</b><br>"
        f"{_fmt_int(stats.python_files)} Python-Dateien · {_fmt_int(stats.total_lines)} Gesamtzeilen · "
        f"{_fmt_int(stats.code_lines)} Codezeilen<br>"
        f"Tests-Paket: {stats.test_package_files} Python-Dateien · {stats.test_files} test_*.py · "
        f"{stats.static_tests} statisch erkannte Tests<br>"
        "Aktueller Dokumentations-/Review-Stand: 13.09.2026 · Refactoring-/Stabilitätsblöcke 1-12 dokumentiert.<br>"
        "Gezielte Regressionen, compileall, Architekturgrenzen und Release-Smoke sichern die geänderten Bereiche; "
        "bekannte Review-Host-Probleme werden getrennt von fachlichen Regressionen geführt.<br><br>"
        "Entwicklungszeit gesamt: rund 6.000 Stunden<br>"
        "V8 → V9: rund 2.000 Stunden · V9 → V9.8: rund 2.000 Stunden · V7 → V8: rund 1.600 Stunden<br>"
        "Testzeit: V1–V7 knapp 150h · V8 rund 400h · V9 bisher rund 140h praktische Felderprobung<br><br>"
        "Vorherige Version V8: 111 Programme · 25.800 Zeilen · 21.200 Codezeilen.<br>"
        "Vorherige Version V7: 6 Programme · 26.568 Zeilen · 19.880 Codezeilen.<br><br>"
        "Shortcuts: F1=Hilfe · F2=Handbuch · F9=Werkzeuge · F11=Legacy V8 · F12=Changelog V9<br>"
        "Strg+W=Tab schließen · Strg+Shift+T=Tab öffnen · Strg+R=Standardwerte · Entf=Datei entfernen"
    )
