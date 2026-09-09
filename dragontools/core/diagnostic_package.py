# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import platform
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from .log_cleanup import (
    LOG_CATEGORY_CRASH,
    LOG_CATEGORY_ERROR,
    LOG_CATEGORY_NORMAL,
    LOG_CATEGORY_VERBOSE,
    _file_category,
)
from .logger import log_base_from_settings, verbose_log_dir_from_settings
from .settings import APP_VERSION
from .settings_backup import _iter_backup_files, dragon_documents_dir, settings_to_dict


def default_diagnostic_package_path(documents_dir: Path | None = None) -> Path:
    root = documents_dir or dragon_documents_dir()
    out_dir = root / "Diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    return out_dir / f"DragonTools_Diagnose_{stamp}.zip"


def create_diagnostic_package(
    target_path: str | Path,
    *,
    settings,
    documents_dir: Path | None = None,
    max_logs_per_category: int = 10,
) -> Path:
    """Erstellt ein lokales Diagnosepaket für Support und Fehlersuche."""
    target = Path(target_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    docs = documents_dir or dragon_documents_dir()
    log_root = log_base_from_settings(settings)
    created_at = datetime.now().isoformat(timespec="seconds")

    manifest = {
        "format": "DragonToolsDiagnosticPackage",
        "format_version": 1,
        "app_version": APP_VERSION,
        "created_at": created_at,
    }

    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        zf.writestr("diagnose_info.txt", _diagnose_info(created_at, log_root, docs))
        zf.writestr(
            "settings.json",
            json.dumps(settings_to_dict(settings, mask_sensitive=True), indent=2, ensure_ascii=False),
        )
        zf.writestr("tools.txt", _tool_diagnostics_text())
        zf.writestr("extended_systemtest.txt", _extended_systemtest_text())

        for file_path in _selected_log_files(
            log_root,
            max_logs_per_category=max_logs_per_category,
        ):
            category = _file_category(file_path)
            arc = f"logs/{category}/{_safe_arcname(file_path)}"
            _write_existing_file(zf, file_path, arc)

        verbose_dir = verbose_log_dir_from_settings(settings)
        for file_path in _latest_files(verbose_dir, max_logs_per_category):
            arc = f"logs/{LOG_CATEGORY_VERBOSE}/{_safe_arcname(file_path)}"
            _write_existing_file(zf, file_path, arc)

        for path, arcname in _iter_backup_files(docs):
            _write_existing_file(zf, path, f"config/{arcname}")

        for file_path in _latest_job_journals(docs, limit=5):
            _write_existing_file(zf, file_path, f"job_journal/{_safe_arcname(file_path)}")

    return target


def _diagnose_info(created_at: str, log_root: Path, documents_dir: Path) -> str:
    lines = [
        f"DragonTools Diagnosepaket V{APP_VERSION}",
        "=" * 80,
        f"Erstellt: {created_at}",
        f"Python: {sys.version}",
        f"Executable: {sys.executable}",
        f"System: {platform.platform()}",
        f"Log-Basisordner: {log_root}",
        f"DragonTools-Dokumentordner: {documents_dir}",
        "",
        "Hinweis:",
        "Dieses Paket enthält lokale Pfade und Dateinamen aus Logs, damit Fehler nachvollziehbar bleiben.",
    ]
    return "\n".join(lines) + "\n"


def _diagnostic_tool_paths() -> dict[str, str]:
    from .paths import get_tool_paths

    tools = get_tool_paths()
    return {
        "ffmpeg": tools.ffmpeg,
        "ffprobe": tools.ffprobe,
        "mkvmerge": tools.mkvmerge,
        "mkvextract": tools.mkvextract,
        "makemkvcon": tools.makemkvcon,
        "mediainfo": tools.mediainfo,
        "dovi_tool": tools.dovi_tool,
        "hdr10plus_tool": tools.hdr10plus_tool,
        "mp4box": tools.mp4box,
        "handbrake": tools.handbrake_cli,
        "rmts": tools.rmts,
    }


def _tool_diagnostics_text() -> str:
    try:
        from .tool_diagnostics import build_tool_diagnostics, format_tool_diagnostics

        return format_tool_diagnostics(build_tool_diagnostics(_diagnostic_tool_paths())) + "\n"
    except Exception as exc:
        return f"Werkzeugdiagnose konnte nicht erstellt werden: {exc}\n"


def _extended_systemtest_text() -> str:
    try:
        from .tool_diagnostics import format_extended_system_test, run_extended_system_test

        return format_extended_system_test(run_extended_system_test(_diagnostic_tool_paths())) + "\n"
    except Exception as exc:
        return f"Erweiterter Systemtest konnte nicht erstellt werden: {exc}\n"


def _selected_log_files(log_root: Path, *, max_logs_per_category: int) -> list[Path]:
    logging_root = log_root / "Logging"
    if not logging_root.exists():
        return []
    buckets: dict[str, list[Path]] = {
        LOG_CATEGORY_NORMAL: [],
        LOG_CATEGORY_ERROR: [],
        LOG_CATEGORY_CRASH: [],
    }
    for file_path in logging_root.rglob("*"):
        if not file_path.is_file() or file_path.name == "crash_state.json":
            continue
        category = _file_category(file_path)
        if category in buckets:
            buckets[category].append(file_path)
    selected: list[Path] = []
    for category in (LOG_CATEGORY_NORMAL, LOG_CATEGORY_ERROR, LOG_CATEGORY_CRASH):
        selected.extend(_latest_from_list(buckets[category], max_logs_per_category))
    return selected


def _latest_files(folder: Path, limit: int) -> list[Path]:
    if not folder.exists():
        return []
    return _latest_from_list([p for p in folder.glob("*.txt") if p.is_file()], limit)


def _latest_job_journals(documents_dir: Path, *, limit: int) -> list[Path]:
    folder = documents_dir / "JobJournal"
    if not folder.exists():
        return []
    files = [p for p in folder.glob("*.json") if p.is_file()]
    archive = folder / "Abgeschlossen"
    if archive.exists():
        files.extend(p for p in archive.glob("*.json") if p.is_file())
    return _latest_from_list(files, limit)


def _latest_from_list(files: list[Path], limit: int) -> list[Path]:
    return sorted(files, key=lambda p: p.stat().st_mtime, reverse=True)[: max(0, limit)]


def _write_existing_file(zf: zipfile.ZipFile, path: Path, arcname: str) -> None:
    try:
        if path.exists() and path.is_file():
            zf.write(path, arcname)
    except Exception:
        zf.writestr(f"{arcname}.skipped.txt", f"Konnte Datei nicht aufnehmen: {path}\n")


def _safe_arcname(path: Path) -> str:
    parts = [part for part in path.parts if part not in {"", ".", ".."}]
    name = "__".join(parts[-5:]) if parts else path.name
    return "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in name)
