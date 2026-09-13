# -*- coding: utf-8 -*-
"""Release validation orchestration facade.

The concrete checks are grouped by responsibility in dedicated modules while
this module keeps the public validation API stable.
"""
from __future__ import annotations

import sys
from pathlib import Path

from .config_migration import current_schema_version
from .release_validation_common import (
    APP_VERSION,
    ReleaseCheck,
    _check_exists,
    _check_matching_file,
    _check_schema_file,
    _looks_like_app_data_dir,
    _project_root_from_module,
    _resolve_app_dirs,
)
from .release_validation_environment import (
    _check_build_environment,
    _check_ci_workflow,
    _check_dv_hdr_integration_contract,
    _check_opencv_dependency,
    _check_optional_environment,
    _check_runtime_environment,
    _check_test_environment,
)
from .release_validation_package import (
    _check_forbidden_release_artifacts,
    _check_python_package_smoke,
    _find_dist_dir,
    _load_release_manifest,
    _scan_private_markers,
)

def validate_release(
    project_root: str | Path | None = None,
    *,
    dist_root: str | Path | None = None,
    mode: str = "auto",
) -> list[ReleaseCheck]:
    root = Path(project_root) if project_root is not None else _project_root_from_module()
    root = root.resolve()
    normalized_mode = (mode or "auto").lower()
    if normalized_mode not in {"auto", "source", "app"}:
        raise ValueError(f"Unbekannter Release-Prüfmodus: {mode!r}")
    if normalized_mode == "auto":
        normalized_mode = "app" if getattr(sys, "frozen", False) or _looks_like_app_data_dir(root) else "source"
    if normalized_mode == "app":
        return validate_app_bundle(root)

    dist_base = Path(dist_root) if dist_root is not None else None
    checks: list[ReleaseCheck] = []

    manifest, manifest_check = _load_release_manifest(root)
    checks.append(manifest_check)
    manifest_valid = manifest_check.status == "ok"
    profile = str(manifest.get("profile") or "").strip().casefold() if manifest_valid else ""
    package_only = profile == "package-only"
    if package_only:
        checks.append(ReleaseCheck(
            "ok",
            "Quellpaket-Profil",
            "Package-only-Profil: nur Python-Paket, Tests und Release-Metadaten werden erwartet.",
        ))
    else:
        checks.append(_check_exists(root / "DragonToolsV9.py", "Quell-Startdatei"))
    build_inputs_included = (
        bool(manifest.get("build_inputs_included", profile == "source-with-build"))
        if manifest_valid
        else False
    )
    if manifest_valid and build_inputs_included:
        build_strategy = str(manifest.get("build_strategy") or "pyinstaller-spec").strip().casefold()
        build_script_name = str(manifest.get("build_script") or "build_v9.bat").strip()
        build_script = root / build_script_name
        checks.append(_check_exists(build_script, "Build-Skript"))
        if build_strategy == "pyinstaller-cli":
            checks.append(ReleaseCheck(
                "ok",
                "Build-Strategie",
                f"PyInstaller-CLI ueber {build_script_name}; keine .spec-Datei erforderlich.",
            ))
        elif build_strategy == "pyinstaller-spec":
            spec_name = str(manifest.get("spec_file") or f"DragonToolsV{APP_VERSION}.spec").strip()
            checks.append(_check_exists(root / spec_name, "Versionierte PyInstaller-Spec"))
        else:
            checks.append(ReleaseCheck(
                "error",
                "Build-Strategie",
                f"Unbekannte Build-Strategie: {build_strategy!r}",
            ))
        compatibility_script = str(manifest.get("compatibility_build_script") or "").strip()
        if compatibility_script:
            checks.append(_check_exists(root / compatibility_script, "Kompatibilitaets-Build-Skript", required=False))
        if bool(manifest.get("external_build_assets_included", True)):
            checks.append(_check_exists(root / "Bilder" / "splash_pyinstaller.png", "PyInstaller-Boot-Splash", required=False))
        else:
            checks.append(ReleaseCheck(
                "ok",
                "Externe Build-Artefakte",
                "Source-Archiv enthaelt bewusst nicht alle grossen Build-/Tool-Artefakte; das Build-Skript prueft sie lokal fail-fast.",
            ))
    elif manifest_valid:
        checks.append(ReleaseCheck(
            "ok",
            "Build-Quelldateien",
            f"{profile}-Profil: lokale PyInstaller-Spec, Build-Skript und Boot-Splash sind laut Manifest nicht Bestandteil dieses Archivs.",
        ))
    else:
        checks.append(_check_exists(root / f"DragonToolsV{APP_VERSION}.spec", "Versionierte PyInstaller-Spec", required=False))
        checks.append(_check_exists(root / "build_v9.bat", "Build-Skript", required=False))
        checks.append(_check_exists(root / "Bilder" / "splash_pyinstaller.png", "PyInstaller-Boot-Splash", required=False))
    if package_only:
        checks.append(ReleaseCheck(
            "ok",
            "Anwendungsartefakte",
            "Package-only-Profil: Entry-Point, Help, Handbuch und Changelog sind nicht Bestandteil dieses Quellpakets.",
        ))
    else:
        checks.append(_check_exists(root / "help.html", "Help-Datei"))
        checks.append(_check_exists(root / "DragonToolsV9_Dokumentation.docx", "Dokumentationsquelle", required=False))
        manual_required = bool(manifest.get("manual_pdf_included", True)) if manifest_valid else True
        checks.append(_check_exists(root / "Handbuch" / "Handbuch.pdf", "PDF-Handbuch", required=manual_required))
        checks.append(_check_exists(root / "Aenderungshistorie" / "CHANGELOG.json", "V9-Änderungshistorie (JSON)"))
        checks.append(_check_exists(root / "Aenderungshistorie" / "CHANGELOG.txt", "V9-Änderungshistorie (TXT-Fallback)", required=False))
        checks.append(_check_exists(root / "Aenderungshistorie" / "CHANGELOGV8.txt", "Legacy V8-Änderungshistorie", required=False))
        checks.append(_check_exists(root / "Aenderungshistorie" / "CHANGELOGV7.txt", "Legacy V7-Änderungshistorie", required=False))

    config_dir = root / "dragontools" / "config"
    checks.extend([
        _check_schema_file(
            config_dir / "default_audio_rules.json",
            current_schema_version("audio_rules"),
            "Schema: Audio-Regeln",
        ),
        _check_schema_file(
            config_dir / "default_subtitle_rules.json",
            current_schema_version("subtitle_rules"),
            "Schema: Untertitel-Regeln",
        ),
        _check_schema_file(
            config_dir / "default_move_rules.json",
            current_schema_version("move_rules"),
            "Schema: Move-Regeln",
        ),
        _check_schema_file(
            config_dir / "default_renamer_rules.json",
            current_schema_version("renamer_rules"),
            "Schema: Renamer-Regeln",
        ),
        _check_schema_file(
            config_dir / "default_profiles.json",
            current_schema_version("profiles"),
            "Schema: Profile",
        ),
    ])
    checks.append(_check_python_package_smoke(root))
    checks.append(_check_forbidden_release_artifacts(root))
    if manifest_valid and bool(manifest.get("runtime_environment_included", False)):
        checks.append(_check_runtime_environment(root))
    if manifest_valid and bool(manifest.get("optional_environment_included", False)):
        checks.append(_check_optional_environment(root))
    if manifest_valid and bool(manifest.get("test_environment_included", False)):
        checks.append(_check_test_environment(root))
    if manifest_valid and bool(manifest.get("build_environment_included", False)):
        checks.append(_check_build_environment(root))
    if manifest_valid and bool(manifest.get("ci_workflow_included", False)):
        checks.append(_check_ci_workflow(root))
    if manifest_valid and bool(manifest.get("dv_hdr_integration_tests_included", False)):
        checks.append(_check_dv_hdr_integration_contract(root))
    checks.append(_check_opencv_dependency())

    dist_dir = _find_dist_dir(root, dist_base)
    if dist_dir is None:
        if profile in {"source-only", "package-only"}:
            checks.append(ReleaseCheck(
                "ok",
                "PyInstaller-Build",
                f"{profile}-Profil: dist-Build ist nicht Bestandteil dieses Quellarchivs.",
            ))
        else:
            checks.append(ReleaseCheck("warn", "PyInstaller-Build", f"Kein Build-Ordner unter {(dist_base or root / 'dist')} gefunden."))
    else:
        checks.append(ReleaseCheck("ok", "PyInstaller-Build", str(dist_dir)))
        checks.append(_check_exists(dist_dir / f"DragonToolsV{APP_VERSION}.exe", "Build: EXE"))
        checks.append(_check_exists(dist_dir / "Daten", "Build: Datenordner"))
        checks.append(_check_exists(dist_dir / "Daten" / "dragontools" / "config", "Build: Runtime-Konfiguration"))
        checks.append(_check_exists(dist_dir / "Daten" / "Python" / "dragontools", "Build: Python-Quellpaket"))
        checks.append(_check_exists(dist_dir / "Daten" / "Handbuch" / "Handbuch.pdf", "Build: Handbuch"))
        checks.append(_check_exists(dist_dir / "Daten" / "help.html", "Build: Help-Datei"))
        checks.append(_check_exists(dist_dir / "Daten" / "Aenderungshistorie" / "CHANGELOG.json", "Build: Changelog JSON"))
        checks.append(_check_exists(dist_dir / "Daten" / "Aenderungshistorie" / "CHANGELOG.txt", "Build: Changelog TXT-Fallback", required=False))

        # Existenz allein reicht bei Dokumenten nicht: Ein alter dist-Ordner kann
        # formal vollständig sein, aber noch Help/Handbuch/Changelog eines
        # früheren Quellstands enthalten. Der Source-Check vergleicht deshalb
        # die tatsächlich eingebundenen Artefakte bytegenau.
        checks.append(_check_matching_file(
            root / "help.html",
            dist_dir / "Daten" / "help.html",
            "Build: Help-Aktualität",
        ))
        checks.append(_check_matching_file(
            root / "Handbuch" / "Handbuch.pdf",
            dist_dir / "Daten" / "Handbuch" / "Handbuch.pdf",
            "Build: Handbuch-Aktualität",
        ))
        checks.append(_check_matching_file(
            root / "Aenderungshistorie" / "CHANGELOG.json",
            dist_dir / "Daten" / "Aenderungshistorie" / "CHANGELOG.json",
            "Build: Changelog-JSON-Aktualität",
        ))
        source_changelog_txt = root / "Aenderungshistorie" / "CHANGELOG.txt"
        built_changelog_txt = dist_dir / "Daten" / "Aenderungshistorie" / "CHANGELOG.txt"
        if source_changelog_txt.exists() or built_changelog_txt.exists():
            checks.append(_check_matching_file(
                source_changelog_txt,
                built_changelog_txt,
                "Build: Changelog-TXT-Aktualität",
            ))

        checks.append(_check_exists(dist_dir / "Daten" / "Programme", "Build: Programme/Tools", required=False))
        checks.append(_check_python_package_smoke(dist_dir / "Daten" / "Python", "Build: Python-Paket-Smoke-Test"))
        dist_bytecode_check = _check_forbidden_release_artifacts(dist_dir / "Daten")
        checks.append(ReleaseCheck(
            dist_bytecode_check.status,
            "Build: Release-Bytecode",
            dist_bytecode_check.detail,
        ))

    checks.extend(_scan_private_markers(root))
    return checks


def validate_app_bundle(app_root: str | Path | None = None) -> list[ReleaseCheck]:
    app_dir, data_dir = _resolve_app_dirs(Path(app_root) if app_root is not None else None)
    checks: list[ReleaseCheck] = []

    checks.append(_check_exists(app_dir / f"DragonToolsV{APP_VERSION}.exe", "Startdatei"))
    checks.append(_check_exists(data_dir, "Datenordner"))
    checks.append(_check_exists(data_dir / "help.html", "Help-Datei"))
    checks.append(_check_exists(data_dir / "Handbuch" / "Handbuch.pdf", "PDF-Handbuch"))
    checks.append(_check_exists(data_dir / "Aenderungshistorie" / "CHANGELOG.json", "V9-Änderungshistorie (JSON)"))
    checks.append(_check_exists(data_dir / "Aenderungshistorie" / "CHANGELOG.txt", "V9-Änderungshistorie (TXT-Fallback)", required=False))
    checks.append(_check_exists(data_dir / "Aenderungshistorie" / "CHANGELOGV8.txt", "Legacy V8-Änderungshistorie", required=False))
    checks.append(_check_exists(data_dir / "Aenderungshistorie" / "CHANGELOGV7.txt", "Legacy V7-Änderungshistorie", required=False))
    # PyInstaller importiert die Python-Module in sein internes Archiv. Für
    # Diagnose/Quellreferenz legt der Builder zusätzlich eine lesbare Kopie unter
    # Daten\Python\dragontools ab. Daten\dragontools enthält dagegen nur
    # Runtime-Daten wie die JSON-Konfiguration. Beide Bereiche werden deshalb
    # getrennt geprüft.
    checks.append(_check_exists(data_dir / "dragontools" / "config", "Runtime-Konfiguration"))
    checks.append(_check_exists(data_dir / "Python" / "dragontools", "Python-Quellpaket"))
    checks.append(_check_exists(data_dir / "Programme", "Programme/Tools", required=False))

    config_dir = data_dir / "dragontools" / "config"
    checks.extend([
        _check_schema_file(
            config_dir / "default_audio_rules.json",
            current_schema_version("audio_rules"),
            "Schema: Audio-Regeln",
        ),
        _check_schema_file(
            config_dir / "default_subtitle_rules.json",
            current_schema_version("subtitle_rules"),
            "Schema: Untertitel-Regeln",
        ),
        _check_schema_file(
            config_dir / "default_move_rules.json",
            current_schema_version("move_rules"),
            "Schema: Move-Regeln",
        ),
        _check_schema_file(
            config_dir / "default_renamer_rules.json",
            current_schema_version("renamer_rules"),
            "Schema: Renamer-Regeln",
        ),
        _check_schema_file(
            config_dir / "default_profiles.json",
            current_schema_version("profiles"),
            "Schema: Profile",
        ),
    ])
    checks.append(_check_python_package_smoke(data_dir / "Python"))
    checks.append(_check_forbidden_release_artifacts(data_dir))
    checks.append(_check_opencv_dependency())
    return checks


def _stdout_supports_status_icons() -> bool:
    try:
        "✅⚠️❌ℹ️".encode(getattr(sys.stdout, "encoding", None) or "utf-8")
    except (LookupError, UnicodeError):
        return False
    return True


def format_release_checks(checks: list[ReleaseCheck], *, plain: bool | None = None) -> str:
    use_plain = not _stdout_supports_status_icons() if plain is None else plain
    icons = {"ok": "[OK]", "warn": "[WARN]", "error": "[FEHLER]"} if use_plain else {"ok": "✅", "warn": "⚠️", "error": "❌"}
    lines = ["Release-/Build-Prüfung – Dragon Tools", ""]
    for check in checks:
        icon = icons.get(check.status, "[INFO]" if use_plain else "ℹ️")
        lines.append(f"{icon} {check.title}")
        if check.detail:
            lines.append(f"   {check.detail}")
    errors = sum(1 for item in checks if item.status == "error")
    warnings = sum(1 for item in checks if item.status == "warn")
    lines.extend(["", f"Ergebnis: {errors} Fehler, {warnings} Warnungen"])
    return "\n".join(lines)


__all__ = ["ReleaseCheck", "format_release_checks", "validate_app_bundle", "validate_release"]
