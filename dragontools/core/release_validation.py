# -*- coding: utf-8 -*-
"""Stable public facade for release validation."""
from __future__ import annotations

import sys
from pathlib import Path

from .release_validation_app import validate_app_bundle
from .release_validation_common import ReleaseCheck, _looks_like_app_data_dir, _project_root_from_module
from .release_validation_environment import (
    _check_build_environment,
    _check_ci_workflow,
    _check_dv_hdr_integration_contract,
    _check_optional_environment,
    _check_runtime_environment,
    _check_test_environment,
)
from .release_validation_source import validate_source_release


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
    return validate_source_release(root, dist_root=dist_base)


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
