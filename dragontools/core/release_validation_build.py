# -*- coding: utf-8 -*-
"""Validation of an already built PyInstaller distribution."""
from __future__ import annotations

from pathlib import Path

from .release_validation_common import APP_VERSION, ReleaseCheck, _check_exists, _check_matching_file
from .release_validation_package import _check_forbidden_release_artifacts, _check_python_package_smoke, _find_dist_dir


def validate_dist_bundle(
    root: Path,
    *,
    dist_root: Path | None,
    profile: str,
) -> list[ReleaseCheck]:
    checks: list[ReleaseCheck] = []
    dist_dir = _find_dist_dir(root, dist_root)
    if dist_dir is None:
        if profile in {"source-only", "package-only"}:
            return [ReleaseCheck("ok", "PyInstaller-Build", f"{profile}-Profil: dist-Build ist nicht Bestandteil dieses Quellarchivs.")]
        return [ReleaseCheck("warn", "PyInstaller-Build", f"Kein Build-Ordner unter {(dist_root or root / 'dist')} gefunden.")]

    checks.extend([
        ReleaseCheck("ok", "PyInstaller-Build", str(dist_dir)),
        _check_exists(dist_dir / f"DragonToolsV{APP_VERSION}.exe", "Build: EXE"),
        _check_exists(dist_dir / "Daten", "Build: Datenordner"),
        _check_exists(dist_dir / "Daten" / "dragontools" / "config", "Build: Runtime-Konfiguration"),
        _check_exists(dist_dir / "Daten" / "Python" / "dragontools", "Build: Python-Quellpaket"),
        _check_exists(dist_dir / "Daten" / "Handbuch" / "Handbuch.pdf", "Build: Handbuch"),
        _check_exists(dist_dir / "Daten" / "help.html", "Build: Help-Datei"),
        _check_exists(dist_dir / "Daten" / "Aenderungshistorie" / "CHANGELOG.json", "Build: Changelog JSON"),
        _check_exists(dist_dir / "Daten" / "Aenderungshistorie" / "CHANGELOG.txt", "Build: Changelog TXT-Fallback", required=False),
    ])
    checks.extend(_documentation_freshness_checks(root, dist_dir))
    checks.append(_check_exists(dist_dir / "Daten" / "Programme", "Build: Programme/Tools", required=False))
    checks.append(_check_python_package_smoke(dist_dir / "Daten" / "Python", "Build: Python-Paket-Smoke-Test"))
    bytecode = _check_forbidden_release_artifacts(dist_dir / "Daten")
    checks.append(ReleaseCheck(bytecode.status, "Build: Release-Bytecode", bytecode.detail))
    return checks


def _documentation_freshness_checks(root: Path, dist_dir: Path) -> list[ReleaseCheck]:
    checks = [
        _check_matching_file(root / "help.html", dist_dir / "Daten" / "help.html", "Build: Help-Aktualität"),
        _check_matching_file(
            root / "Handbuch" / "Handbuch.pdf",
            dist_dir / "Daten" / "Handbuch" / "Handbuch.pdf",
            "Build: Handbuch-Aktualität",
        ),
        _check_matching_file(
            root / "Aenderungshistorie" / "CHANGELOG.json",
            dist_dir / "Daten" / "Aenderungshistorie" / "CHANGELOG.json",
            "Build: Changelog-JSON-Aktualität",
        ),
    ]
    source_txt = root / "Aenderungshistorie" / "CHANGELOG.txt"
    built_txt = dist_dir / "Daten" / "Aenderungshistorie" / "CHANGELOG.txt"
    if source_txt.exists() or built_txt.exists():
        checks.append(_check_matching_file(source_txt, built_txt, "Build: Changelog-TXT-Aktualität"))
    return checks
