# -*- coding: utf-8 -*-
"""Validation of an installed/frozen DragonTools application bundle."""
from __future__ import annotations

from pathlib import Path

from .config_migration import current_schema_version
from .release_validation_common import APP_VERSION, ReleaseCheck, _check_exists, _check_schema_file, _resolve_app_dirs
from .release_validation_build import _check_no_python_source_bundle
from .release_validation_environment import _check_opencv_dependency
from .release_validation_package import _check_forbidden_release_artifacts


def validate_app_bundle(app_root: str | Path | None = None) -> list[ReleaseCheck]:
    app_dir, data_dir = _resolve_app_dirs(Path(app_root) if app_root is not None else None)
    checks: list[ReleaseCheck] = [
        _check_exists(app_dir / f"DragonToolsV{APP_VERSION}.exe", "Startdatei"),
        _check_exists(data_dir, "Datenordner"),
        _check_exists(data_dir / "help.html", "Help-Datei"),
        _check_exists(data_dir / "Handbuch" / "Handbuch.pdf", "PDF-Handbuch"),
        _check_exists(data_dir / "Aenderungshistorie" / "CHANGELOG.json", "V9-Änderungshistorie (JSON)"),
        _check_exists(data_dir / "Aenderungshistorie" / "CHANGELOG.txt", "V9-Änderungshistorie (TXT-Fallback)", required=False),
        _check_exists(data_dir / "Aenderungshistorie" / "CHANGELOGV8.txt", "Legacy V8-Änderungshistorie", required=False),
        _check_exists(data_dir / "Aenderungshistorie" / "CHANGELOGV7.txt", "Legacy V7-Änderungshistorie", required=False),
        _check_exists(data_dir / "dragontools" / "config", "Runtime-Konfiguration"),
        _check_no_python_source_bundle(data_dir, "Python-Quellcode"),
        _check_exists(data_dir / "Programme", "Programme/Tools", required=False),
    ]
    checks.extend(_schema_checks(data_dir / "dragontools" / "config"))
    checks.extend([
        _check_forbidden_release_artifacts(data_dir),
        _check_opencv_dependency(),
    ])
    return checks


def _schema_checks(config_dir: Path) -> list[ReleaseCheck]:
    return [
        _check_schema_file(config_dir / "default_audio_rules.json", current_schema_version("audio_rules"), "Schema: Audio-Regeln"),
        _check_schema_file(config_dir / "default_subtitle_rules.json", current_schema_version("subtitle_rules"), "Schema: Untertitel-Regeln"),
        _check_schema_file(config_dir / "default_move_rules.json", current_schema_version("move_rules"), "Schema: Move-Regeln"),
        _check_schema_file(config_dir / "default_renamer_rules.json", current_schema_version("renamer_rules"), "Schema: Renamer-Regeln"),
        _check_schema_file(config_dir / "default_profiles.json", current_schema_version("profiles"), "Schema: Profile"),
    ]
