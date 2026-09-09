# -*- coding: utf-8 -*-
from __future__ import annotations

import faulthandler
import json
import os
import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any

from .json_io import atomic_write_json
from .logger import log_base_from_settings, make_log_dir

_STATE_FILE_NAME = "crash_state.json"

_installed = False
_state_dir: Path | None = None
_state_file: Path | None = None
_fatal_log_file: Path | None = None
_fatal_log_handle = None
_old_excepthook = None
_old_threading_excepthook = None
_state_lock = threading.RLock()


def _fallback_diagnostic(message: str, exc: BaseException | None = None) -> None:
    """Minimaler Diagnosepfad, der selbst keine normale Logging-Infrastruktur braucht."""
    suffix = f": {exc}" if exc is not None else ""
    streams = (getattr(sys, "stderr", None), getattr(sys, "__stderr__", None))
    for stream in streams:
        if stream is None:
            continue
        try:
            print(f"[DragonTools CrashGuard] {message}{suffix}", file=stream, flush=True)
            return
        except Exception:
            continue
    # Crash-Diagnose darf den eigentlichen Programmablauf nie blockieren.


def install_crash_guard(app_version: str = "") -> Path | None:
    """Installiert globale Diagnose-Hooks fuer unerwartete Programmabbrueche."""
    global _installed, _state_dir, _state_file, _fatal_log_file, _fatal_log_handle
    global _old_excepthook, _old_threading_excepthook

    if _installed:
        return _state_dir

    try:
        _state_dir = make_log_dir(log_base_from_settings()) / "CrashReports"
        _state_dir.mkdir(parents=True, exist_ok=True)
        _state_file = _state_dir / _STATE_FILE_NAME
        _report_unclean_previous_run(app_version)

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        _fatal_log_file = _state_dir / f"{ts}_fatal_runtime.txt"
        _fatal_log_handle = open(_fatal_log_file, "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=_fatal_log_handle, all_threads=True)

        _old_excepthook = sys.excepthook
        sys.excepthook = _handle_unhandled_exception
        if hasattr(threading, "excepthook"):
            _old_threading_excepthook = threading.excepthook
            threading.excepthook = _handle_thread_exception

        _installed = True
        mark_activity(
            "App gestartet",
            extra={
                "app_version": app_version,
                "fatal_log": str(_fatal_log_file),
            },
        )
        return _state_dir
    except Exception:
        # Crash-Diagnose darf den Programmstart niemals verhindern.
        return None


def mark_activity(
    stage: str,
    *,
    file_path: str | Path | None = None,
    command: list[Any] | str | None = None,
    extra: dict[str, Any] | None = None,
) -> bool:
    """Speichert den letzten bekannten Arbeitsschritt atomar.

    Der CrashGuard bleibt fail-soft, liefert aber einen Status und meldet
    Schreibfehler über einen minimalen stderr-Fallback statt sie still zu
    verschlucken.
    """
    if _state_file is None:
        return False
    try:
        data = {
            "active": True,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "pid": os.getpid(),
            "executable": sys.executable,
            "stage": str(stage or ""),
            "file": str(file_path or ""),
            "command": _normalize_command(command),
            "extra": extra or {},
        }
        # Ein gemeinsamer Lock definiert den Vertrag "letzter abgeschlossener
        # Aufruf gewinnt". atomic_write_json() verwendet zusätzlich für jeden
        # Write einen eigenen Temp-Pfad + fsync, sodass parallele Worker nicht
        # mehr um dieselbe crash_state.tmp konkurrieren können.
        with _state_lock:
            atomic_write_json(_state_file, data)
        return True
    except (OSError, ValueError, TypeError) as exc:
        _fallback_diagnostic("Aktivitätsmarker konnte nicht geschrieben werden", exc)
        return False


def clear_activity() -> bool:
    """Entfernt den aktiven Marker nach sauberem Abschluss und liefert Erfolg."""
    if _state_file is None:
        _cleanup_empty_fatal_log()
        return True
    ok = True
    try:
        with _state_lock:
            _state_file.unlink(missing_ok=True)
    except OSError as exc:
        ok = False
        _fallback_diagnostic("Aktivitätsmarker konnte nicht entfernt werden", exc)
    _cleanup_empty_fatal_log()
    return ok


def write_manual_crash_note(reason: str, *, traceback_text: str = "") -> str:
    """Schreibt einen sofortigen Crash-/Exceptionbericht."""
    report_dir = _ensure_report_dir()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = report_dir / f"{ts}_crash.txt"
    state = _read_state()
    text = _build_report_text(
        title="DragonTools Crashbericht",
        reason=reason,
        state=state,
        traceback_text=traceback_text,
    )
    path.write_text(text, encoding="utf-8")
    return str(path)


def _handle_unhandled_exception(exc_type, exc_value, exc_tb) -> None:
    tb = "".join(traceback.format_exception(exc_type, exc_value, exc_tb))
    try:
        write_manual_crash_note("Unbehandelte Ausnahme im Hauptthread.", traceback_text=tb)
    except Exception:
        pass
    if _old_excepthook:
        _old_excepthook(exc_type, exc_value, exc_tb)


def _handle_thread_exception(args) -> None:
    tb = "".join(
        traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)
    )
    thread_name = getattr(args.thread, "name", "") or "unbekannt"
    try:
        write_manual_crash_note(
            f"Unbehandelte Ausnahme im Nebenthread: {thread_name}",
            traceback_text=tb,
        )
    except Exception:
        pass
    if _old_threading_excepthook:
        _old_threading_excepthook(args)


def _report_unclean_previous_run(app_version: str) -> None:
    if _state_file is None or not _state_file.exists():
        return
    state = _read_state()
    if not state.get("active"):
        _state_file.unlink(missing_ok=True)
        return

    pid = _safe_int(state.get("pid"))
    if pid and pid != os.getpid() and _pid_is_running(pid):
        return

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = _state_file.parent / f"{ts}_unclean_shutdown.txt"
    text = _build_report_text(
        title="DragonTools unvollstaendig beendet",
        reason=(
            "Der vorherige DragonTools-Lauf wurde nicht sauber abgeschlossen. "
            "Das kann auf einen Absturz, einen Prozessabbruch, Windows-Neustart "
            "oder ein hartes Beenden der EXE hinweisen."
        ),
        state=state,
        traceback_text="",
        extra={"current_app_version": app_version},
    )
    path.write_text(text, encoding="utf-8")
    _remove_empty_fatal_log_from_state(state)
    try:
        _state_file.unlink(missing_ok=True)
    except Exception:
        pass


def _build_report_text(
    *,
    title: str,
    reason: str,
    state: dict[str, Any],
    traceback_text: str,
    extra: dict[str, Any] | None = None,
) -> str:
    lines = [
        title,
        "=" * 80,
        f"Zeitpunkt: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
        f"Grund: {reason}",
        "",
        "Letzter bekannter Zustand",
        "-" * 80,
        f"Zeitstempel: {state.get('timestamp', '')}",
        f"PID: {state.get('pid', '')}",
        f"EXE: {state.get('executable', '')}",
        f"Schritt: {state.get('stage', '')}",
        f"Datei: {state.get('file', '')}",
    ]
    command = state.get("command") or []
    if command:
        lines += ["", "Letztes Kommando", "-" * 80]
        if isinstance(command, list):
            lines.append(" ".join(str(part) for part in command))
        else:
            lines.append(str(command))
    state_extra = state.get("extra") or {}
    merged_extra = dict(state_extra)
    if extra:
        merged_extra.update(extra)
    if merged_extra:
        lines += ["", "Zusatzdaten", "-" * 80]
        lines.append(json.dumps(merged_extra, ensure_ascii=False, indent=2))
    if traceback_text:
        lines += ["", "Traceback", "-" * 80, traceback_text.rstrip()]
    lines.append("")
    return "\n".join(lines)


def _ensure_report_dir() -> Path:
    if _state_dir is not None:
        _state_dir.mkdir(parents=True, exist_ok=True)
        return _state_dir
    fallback = Path.home() / "Documents" / "DragonTools" / "Logging" / "CrashReports"
    fallback.mkdir(parents=True, exist_ok=True)
    return fallback


def _cleanup_empty_fatal_log() -> None:
    global _fatal_log_handle
    try:
        if faulthandler.is_enabled():
            faulthandler.disable()
    except Exception:
        pass

    handle = _fatal_log_handle
    _fatal_log_handle = None
    try:
        if handle:
            try:
                handle.flush()
            except Exception:
                pass
            handle.close()
    except Exception:
        pass

    _remove_empty_fatal_log_path(_fatal_log_file)


def _remove_empty_fatal_log_from_state(state: dict[str, Any]) -> None:
    extra = state.get("extra") if isinstance(state, dict) else {}
    if not isinstance(extra, dict):
        return
    _remove_empty_fatal_log_path(extra.get("fatal_log"))


def _remove_empty_fatal_log_path(path_value: str | Path | None) -> None:
    if not path_value:
        return
    try:
        path = Path(path_value)
        if path.name.endswith("_fatal_runtime.txt") and path.exists() and path.stat().st_size == 0:
            path.unlink(missing_ok=True)
    except Exception:
        pass


def _read_state() -> dict[str, Any]:
    if _state_file is None or not _state_file.exists():
        return {}
    try:
        return json.loads(_state_file.read_text(encoding="utf-8") or "{}")
    except Exception:
        return {}


def _normalize_command(command: list[Any] | str | None) -> list[str] | str:
    if command is None:
        return []
    if isinstance(command, str):
        return command
    try:
        return [str(part) for part in command]
    except Exception:
        return str(command)


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None


def _pid_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except Exception:
        return False
