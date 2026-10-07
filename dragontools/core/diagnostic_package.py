# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import hashlib
import os
import tempfile
from contextlib import contextmanager
import platform
import sys
import uuid
import zipfile
from datetime import datetime
from pathlib import Path

from .log_cleanup import (
    LOG_CATEGORY_CRASH,
    LOG_CATEGORY_ERROR,
    LOG_CATEGORY_NORMAL,
    LOG_CATEGORY_VERBOSE,
    _file_category,
    _is_link_or_junction,
)
from .logger import log_base_from_settings, verbose_log_dir_from_settings
from .diagnostic_redaction import collect_settings_secret_values, redact_sensitive_text
from .diagnostic_privacy import DiagnosticSanitizer
from .crash_state_files import is_crash_state_file
from .version import APP_VERSION
from .settings_backup import _iter_backup_files, dragon_documents_dir, settings_to_dict


def default_diagnostic_package_path(documents_dir: Path | None = None) -> Path:
    root = documents_dir or dragon_documents_dir()
    out_dir = root / "Diagnostics"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S_%f")
    return out_dir / f"DragonTools_Diagnose_{stamp}_{uuid.uuid4().hex[:8]}.zip"


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
    # ZipFile(..., "w") follows a pre-existing symlink.  A support-package
    # destination must never be able to truncate an unrelated file.
    if _is_link_or_junction(target):
        raise ValueError(f"Diagnoseziel darf kein Symlink/Junction sein: {target}")
    docs = documents_dir or dragon_documents_dir()
    log_root = log_base_from_settings(settings)
    created_at = datetime.now().isoformat(timespec="seconds")
    secret_values = collect_settings_secret_values(settings)
    verbose_dir = verbose_log_dir_from_settings(settings)
    sanitize = DiagnosticSanitizer(secret_values=secret_values, private_roots=(docs, log_root, verbose_dir))

    manifest = {
        "format": "DragonToolsDiagnosticPackage",
        "format_version": 1,
        "app_version": APP_VERSION,
        "created_at": created_at,
    }

    with _diagnostic_archive(target) as zf:
        zf.writestr("manifest.json", json.dumps(manifest, indent=2, ensure_ascii=False))
        zf.writestr("diagnose_info.txt", sanitize(_diagnose_info(created_at, log_root, docs)))
        zf.writestr(
            "settings.json",
            sanitize(json.dumps(settings_to_dict(settings, mask_sensitive=True), indent=2, ensure_ascii=False)),
        )
        zf.writestr("tools.txt", sanitize(_tool_diagnostics_text()))
        zf.writestr("extended_systemtest.txt", sanitize(_extended_systemtest_text()))

        for file_path in _selected_log_files(
            log_root,
            max_logs_per_category=max_logs_per_category,
        ):
            category = _file_category(file_path)
            arc = f"logs/{category}/{_safe_arcname(file_path)}"
            _write_existing_file(zf, file_path, arc, secret_values=secret_values, sanitize=sanitize, owned_root=log_root / "Logging")

        for file_path in _latest_files(verbose_dir, max_logs_per_category):
            arc = f"logs/{LOG_CATEGORY_VERBOSE}/{_safe_arcname(file_path)}"
            _write_existing_file(zf, file_path, arc, secret_values=secret_values, sanitize=sanitize, owned_root=verbose_dir)

        for path, arcname in _iter_backup_files(docs):
            _write_existing_file(
                zf, path, f"config/{arcname}", secret_values=secret_values, sanitize=sanitize, owned_root=docs
            )

        for file_path in _latest_job_journals(docs, limit=5):
            _write_existing_file(
                zf,
                file_path,
                f"job_journal/{_safe_arcname(file_path)}",
                secret_values=secret_values,
                sanitize=sanitize,
                owned_root=docs / "JobJournal",
            )

    return target


@contextmanager
def _diagnostic_archive(target):
    fd, name = tempfile.mkstemp(prefix=".dragontools-diagnostic-", suffix=".zip", dir=target.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            yield archive
        os.replace(temporary, target)
    finally:
        temporary.unlink(missing_ok=True)


def _has_unowned_link(path, owned_root):
    if owned_root is None:
        return _is_link_or_junction(path)
    try:
        relative = path.relative_to(owned_root)
        if not path.resolve().is_relative_to(owned_root.resolve()):
            return True
    except (OSError, ValueError):
        return True
    candidates = (path, *(owned_root / parent for parent in relative.parents))
    return any(_is_link_or_junction(candidate) for candidate in candidates)


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
        "Private Basisordner und Benutzerprofile werden anonymisiert; Dateinamen bleiben für die Diagnose erhalten.",
    ]
    return "\n".join(lines) + "\n"


def _diagnostic_tool_paths() -> dict[str, str]:
    from .tool_paths import get_tool_paths

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
        "hdr10plus_generator": tools.hdr10plus_generator,
        "davinci_resolve": tools.davinci_resolve,
        "comfyui": tools.comfyui,
        "mp4box": tools.mp4box,
        "handbrake": tools.handbrake,
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
    if not logging_root.exists() or _is_link_or_junction(logging_root):
        return []
    buckets: dict[str, list[Path]] = {
        LOG_CATEGORY_NORMAL: [],
        LOG_CATEGORY_ERROR: [],
        LOG_CATEGORY_CRASH: [],
    }
    for file_path in logging_root.rglob("*"):
        if not file_path.is_file() or is_crash_state_file(file_path):
            continue
        category = _file_category(file_path)
        if category in buckets:
            buckets[category].append(file_path)
    selected: list[Path] = []
    for category in (LOG_CATEGORY_NORMAL, LOG_CATEGORY_ERROR, LOG_CATEGORY_CRASH):
        selected.extend(_latest_from_list(buckets[category], max_logs_per_category))
    return selected


def _latest_files(folder: Path, limit: int) -> list[Path]:
    if not folder.exists() or _is_link_or_junction(folder):
        return []
    return _latest_from_list([p for p in folder.glob("*.txt") if p.is_file()], limit)


def _latest_job_journals(documents_dir: Path, *, limit: int) -> list[Path]:
    folder = documents_dir / "JobJournal"
    if not folder.exists() or _is_link_or_junction(folder):
        return []
    files = [p for p in folder.glob("*.json") if p.is_file()]
    archive = folder / "Abgeschlossen"
    if archive.exists() and not _is_link_or_junction(archive):
        files.extend(p for p in archive.glob("*.json") if p.is_file())
    return _latest_from_list(files, limit)


def _latest_from_list(files: list[Path], limit: int) -> list[Path]:
    ranked: list[tuple[float, Path]] = []
    for path in files:
        try:
            ranked.append((path.stat().st_mtime, path))
        except OSError:
            # Log rotation/cleanup can race with package creation.  One
            # vanished file must not make the whole support bundle fail.
            continue
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [path for _mtime, path in ranked[: max(0, limit)]]


def _write_existing_file(
    zf: zipfile.ZipFile,
    path: Path,
    arcname: str,
    *,
    secret_values: set[str] | None = None,
    sanitize=None,
    owned_root=None,
) -> None:
    sanitize = sanitize or (lambda text: redact_sensitive_text(text, secret_values=secret_values or ()))
    try:
        if path.exists() and path.is_file():
            # Never follow a symlink/junction while building a support bundle.
            # A crafted entry inside Logging/JobJournal/rules must not pull an
            # unrelated local file into a package that may be shared.
            if _has_unowned_link(path, owned_root):
                zf.writestr(
                    f"{arcname}.skipped.txt",
                    sanitize(f"Symlink/Junction wurde aus Sicherheitsgründen übersprungen: {path}\n"),
                )
                return
            # Files selected for diagnostic packages are text logs/JSON.  Do
            # not copy them byte-for-byte: tool output and job journals may
            # contain API keys even though settings.json itself is masked.
            # Stream line-by-line so a very large conversion log does not have
            # to be held in RAM while the package is built.
            with path.open("r", encoding="utf-8", errors="replace") as source:
                with zf.open(arcname, "w") as target:
                    for line in source:
                        redacted = sanitize(line)
                        target.write(redacted.encode("utf-8"))
    except Exception:
        zf.writestr(f"{arcname}.skipped.txt", sanitize(f"Konnte Datei nicht aufnehmen: {path}\n"))


def _safe_arcname(path: Path) -> str:
    token = hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:12]
    name = f"{token}__{path.name}"
    return "".join(ch if ch not in '<>:"/\\|?*' else "_" for ch in name)
