# -*- coding: utf-8 -*-
"""Validation of DragonTools source/package releases."""
from __future__ import annotations

from pathlib import Path

from .config_migration import current_schema_version
from .release_validation_build import validate_dist_bundle
from .release_validation_common import APP_VERSION, ReleaseCheck, _check_exists, _check_schema_file
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
    _load_release_manifest,
    _scan_private_markers,
)


def validate_source_release(root: Path, *, dist_root: Path | None = None) -> list[ReleaseCheck]:
    checks: list[ReleaseCheck] = []
    manifest, manifest_check = _load_release_manifest(root)
    checks.append(manifest_check)
    manifest_valid = manifest_check.status == "ok"
    profile = str(manifest.get("profile") or "").strip().casefold() if manifest_valid else ""
    package_only = profile == "package-only"

    checks.extend(_profile_source_checks(root, manifest, manifest_valid, profile, package_only))
    checks.extend(_schema_checks(root / "dragontools" / "config"))
    checks.extend([
        _check_python_package_smoke(root),
        _check_forbidden_release_artifacts(root),
    ])
    checks.extend(_declared_environment_checks(root, manifest, manifest_valid))
    checks.append(_check_opencv_dependency())
    checks.extend(validate_dist_bundle(root, dist_root=dist_root, profile=profile))
    checks.extend(_scan_private_markers(root))
    return checks


def _profile_source_checks(
    root: Path,
    manifest: dict,
    manifest_valid: bool,
    profile: str,
    package_only: bool,
) -> list[ReleaseCheck]:
    checks: list[ReleaseCheck] = []
    if package_only:
        checks.append(ReleaseCheck("ok", "Quellpaket-Profil", "Package-only-Profil: nur Python-Paket, Tests und Release-Metadaten werden erwartet."))
    else:
        checks.append(_check_exists(root / "DragonToolsV9.py", "Quell-Startdatei"))
    checks.extend(_build_input_checks(root, manifest, manifest_valid, profile))
    checks.extend(_application_artifact_checks(root, manifest, manifest_valid, package_only))
    return checks


def _build_input_checks(root: Path, manifest: dict, manifest_valid: bool, profile: str) -> list[ReleaseCheck]:
    included = bool(manifest.get("build_inputs_included", profile == "source-with-build")) if manifest_valid else False
    if not manifest_valid:
        return [
            _check_exists(root / f"DragonToolsV{APP_VERSION}.spec", "Versionierte PyInstaller-Spec", required=False),
            _check_exists(root / "build_v9.bat", "Build-Skript", required=False),
            _check_exists(root / "Bilder" / "splash_pyinstaller.png", "PyInstaller-Boot-Splash", required=False),
        ]
    if not included:
        return [ReleaseCheck("ok", "Build-Quelldateien", f"{profile}-Profil: lokale PyInstaller-Spec, Build-Skript und Boot-Splash sind laut Manifest nicht Bestandteil dieses Archivs.")]

    strategy = str(manifest.get("build_strategy") or "pyinstaller-spec").strip().casefold()
    script_name = str(manifest.get("build_script") or "build_v9.bat").strip()
    checks = [_check_exists(root / script_name, "Build-Skript")]
    if strategy == "pyinstaller-cli":
        checks.append(ReleaseCheck("ok", "Build-Strategie", f"PyInstaller-CLI ueber {script_name}; keine .spec-Datei erforderlich."))
    elif strategy == "pyinstaller-spec":
        spec_name = str(manifest.get("spec_file") or f"DragonToolsV{APP_VERSION}.spec").strip()
        checks.append(_check_exists(root / spec_name, "Versionierte PyInstaller-Spec"))
    else:
        checks.append(ReleaseCheck("error", "Build-Strategie", f"Unbekannte Build-Strategie: {strategy!r}"))
    compatibility = str(manifest.get("compatibility_build_script") or "").strip()
    if compatibility:
        checks.append(_check_exists(root / compatibility, "Kompatibilitaets-Build-Skript", required=False))
    if bool(manifest.get("external_build_assets_included", True)):
        checks.append(_check_exists(root / "Bilder" / "splash_pyinstaller.png", "PyInstaller-Boot-Splash", required=False))
    else:
        checks.append(ReleaseCheck("ok", "Externe Build-Artefakte", "Source-Archiv enthaelt bewusst nicht alle grossen Build-/Tool-Artefakte; das Build-Skript prueft sie lokal fail-fast."))
    return checks


def _application_artifact_checks(root: Path, manifest: dict, manifest_valid: bool, package_only: bool) -> list[ReleaseCheck]:
    if package_only:
        return [ReleaseCheck("ok", "Anwendungsartefakte", "Package-only-Profil: Entry-Point, Help, Handbuch und Changelog sind nicht Bestandteil dieses Quellpakets.")]
    manual_required = bool(manifest.get("manual_pdf_included", True)) if manifest_valid else True
    return [
        _check_exists(root / "help.html", "Help-Datei"),
        _check_exists(root / "DragonToolsV9_Dokumentation.docx", "Dokumentationsquelle", required=False),
        _check_exists(root / "Handbuch" / "Handbuch.pdf", "PDF-Handbuch", required=manual_required),
        _check_exists(root / "Aenderungshistorie" / "CHANGELOG.json", "V9-Änderungshistorie (JSON)"),
        _check_exists(root / "Aenderungshistorie" / "CHANGELOG.txt", "V9-Änderungshistorie (TXT-Fallback)", required=False),
        _check_exists(root / "Aenderungshistorie" / "CHANGELOGV8.txt", "Legacy V8-Änderungshistorie", required=False),
        _check_exists(root / "Aenderungshistorie" / "CHANGELOGV7.txt", "Legacy V7-Änderungshistorie", required=False),
        _check_exists(root / "dragon_hdr10plus_generator" / "pyproject.toml", "Dragon HDR10+ Generator: Projektdefinition"),
        _check_exists(root / "dragon_hdr10plus_generator" / "src" / "dragon_hdr10plus_generator" / "cli.py", "Dragon HDR10+ Generator: CLI"),
        _check_exists(root / "dragontools" / "worker" / "comfyui_client.py", "ComfyUI: lokaler API-Client"),
        _check_exists(root / "dragontools" / "core" / "comfyui_workflow.py", "ComfyUI: Workflow-Vertrag"),
        _check_exists(root / "dragontools" / "core" / "comfyui_hdr_models.py", "ComfyUI: HDR-Modellprofile"),
        _check_exists(root / "dragontools" / "worker" / "comfyui_runtime.py", "ComfyUI: Modell-Readiness"),
        _check_exists(root / "dragontools" / "worker" / "comfyui_video_worker.py", "ComfyUI: Voll-Datei-Worker"),
        _check_exists(root / "extras" / "comfyui" / "DragonTools_HDRTVDM" / "nodes.py", "ComfyUI: HDRTVDM-Bridge-Nodes"),
        _check_exists(root / "COMFYUI_HDR_SETUP.md", "ComfyUI: HDRTVDM-Setup-Anleitung"),
    ]


def _schema_checks(config_dir: Path) -> list[ReleaseCheck]:
    return [
        _check_schema_file(config_dir / "default_audio_rules.json", current_schema_version("audio_rules"), "Schema: Audio-Regeln"),
        _check_schema_file(config_dir / "default_subtitle_rules.json", current_schema_version("subtitle_rules"), "Schema: Untertitel-Regeln"),
        _check_schema_file(config_dir / "default_move_rules.json", current_schema_version("move_rules"), "Schema: Move-Regeln"),
        _check_schema_file(config_dir / "default_renamer_rules.json", current_schema_version("renamer_rules"), "Schema: Renamer-Regeln"),
        _check_schema_file(config_dir / "default_profiles.json", current_schema_version("profiles"), "Schema: Profile"),
    ]


def _declared_environment_checks(root: Path, manifest: dict, manifest_valid: bool) -> list[ReleaseCheck]:
    if not manifest_valid:
        return []
    declared = (
        ("runtime_environment_included", _check_runtime_environment),
        ("optional_environment_included", _check_optional_environment),
        ("test_environment_included", _check_test_environment),
        ("build_environment_included", _check_build_environment),
        ("ci_workflow_included", _check_ci_workflow),
        ("dv_hdr_integration_tests_included", _check_dv_hdr_integration_contract),
    )
    return [checker(root) for flag, checker in declared if bool(manifest.get(flag, False))]
