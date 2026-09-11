# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path

from .config_migration import current_schema_version
from .settings import APP_VERSION

@dataclass(frozen=True)
class ReleaseCheck:
    status: str
    title: str
    detail: str = ""


def _project_root_from_module() -> Path:
    return Path(__file__).resolve().parents[2]


def _looks_like_app_data_dir(path: Path) -> bool:
    return path.name.lower() == "daten" and (path.parent / f"DragonToolsV{APP_VERSION}.exe").exists()


def _resolve_app_dirs(root: Path | None = None) -> tuple[Path, Path]:
    """Returns ``(app_dir, data_dir)`` for a PyInstaller onedir bundle."""
    if root is not None:
        candidate = root.resolve()
        if candidate.name.lower() == "daten":
            return candidate.parent, candidate
        if (candidate / "Daten").exists():
            return candidate, candidate / "Daten"
        return candidate, candidate / "Daten"

    if getattr(sys, "frozen", False):
        app_dir = Path(sys.executable).resolve().parent
        return app_dir, app_dir / "Daten"

    module_root = _project_root_from_module().resolve()
    if _looks_like_app_data_dir(module_root):
        return module_root.parent, module_root
    return module_root, module_root / "Daten"


def _check_exists(path: Path, title: str, *, required: bool = True) -> ReleaseCheck:
    if path.exists():
        return ReleaseCheck("ok", title, str(path))
    return ReleaseCheck("error" if required else "warn", title, f"Nicht gefunden: {path}")


def _load_json(path: Path) -> dict:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}




def _check_matching_file(source: Path, built: Path, title: str) -> ReleaseCheck:
    """Verify that a built documentation artifact matches its source byte-for-byte."""
    if not source.exists() or not built.exists():
        missing = []
        if not source.exists():
            missing.append(f"Quelle fehlt: {source}")
        if not built.exists():
            missing.append(f"Build fehlt: {built}")
        return ReleaseCheck("warn", title, "; ".join(missing))
    try:
        source_bytes = source.read_bytes()
        built_bytes = built.read_bytes()
    except OSError as exc:
        return ReleaseCheck("error", title, f"Vergleich fehlgeschlagen: {exc}")
    if source_bytes == built_bytes:
        return ReleaseCheck("ok", title, f"Build entspricht Quelle: {source.name}")
    return ReleaseCheck(
        "error",
        title,
        f"Build-Datei ist veraltet oder abweichend: {built} (Quelle: {source})",
    )

def _check_schema_file(path: Path, expected_version: int, title: str) -> ReleaseCheck:
    if not path.exists():
        return ReleaseCheck("error", title, f"Nicht gefunden: {path}")
    data = _load_json(path)
    version = data.get("_schema_version")
    if version == expected_version:
        return ReleaseCheck("ok", title, f"Schema {version}: {path.name}")
    return ReleaseCheck("error", title, f"Schema erwartet {expected_version}, gefunden {version!r}: {path}")
