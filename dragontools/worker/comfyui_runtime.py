# -*- coding: utf-8 -*-
"""Readiness and optional auto-start for the local ComfyUI SDR->HDR backend."""
from __future__ import annotations

import os
import subprocess
import threading
import time
from pathlib import Path

from ..core.comfyui_hdr_models import (
    HDRTVDM_PROFILE,
    node_classes_available,
    required_node_classes,
    resolve_comfyui_model_assets,
    resolve_comfyui_workflow,
)
from .comfyui_client import ComfyUIClient
from .hdr10plus_generator_client import generator_executable_available


_COMFYUI_START_LOCK = threading.Lock()
_COMFYUI_START_ATTEMPTS: dict[str, float] = {}
_COMMON_PORTABLE_LAUNCHERS = (
    "run_nvidia_gpu.bat",
    "run_nvidia_gpu_fast_fp16_accumulation.bat",
    "run_cpu.bat",
)


def configure_comfyui_runtime(worker, tools, options: dict) -> None:
    install_marker = str(getattr(tools, "comfyui", "") or "")
    options["_comfyui_installation_available"] = generator_executable_available(install_marker)

    base_url = str(options.get("comfyui_base_url") or "http://127.0.0.1:8188")
    client = ComfyUIClient(base_url, timeout_s=2.0)
    health = client.health()
    if not health.success and bool(options.get("comfyui_auto_start", True)):
        health = _auto_start_and_wait(worker, tools, options, client, initial_health=health)

    options["_comfyui_api_available"] = bool(health.success)
    options["_comfyui_version"] = health.version
    options["_comfyui_device"] = health.device
    options["_comfyui_vram_total"] = health.vram_total

    profile = str(options.get("comfyui_model_profile") or HDRTVDM_PROFILE).strip().lower()
    options["_comfyui_model_profile"] = profile
    assets = resolve_comfyui_model_assets(
        profile,
        repository=options.get("comfyui_model_root"),
        checkpoint=options.get("comfyui_checkpoint"),
    )
    options["_comfyui_model_assets_ready"] = assets.ready
    options["_comfyui_model_repository"] = assets.repository
    options["_comfyui_model_checkpoint"] = assets.checkpoint
    options["_comfyui_model_error"] = assets.error

    workflow = resolve_comfyui_workflow(
        profile,
        workflow_path=options.get("comfyui_workflow_path"),
    )
    options["_comfyui_workflow_valid"] = workflow.ready
    options["_comfyui_workflow_error"] = workflow.error
    options["_comfyui_workflow_warning"] = workflow.warning
    options["_comfyui_workflow_source"] = workflow.source
    options["_comfyui_effective_workflow_path"] = (
        workflow.configured_path if workflow.source == "custom" else ""
    )

    nodes_ready = False
    missing_nodes: tuple[str, ...] = ()
    if health.success:
        required = required_node_classes(profile)
        if not required:
            nodes_ready = True
        else:
            info = client.object_info()
            if info.success:
                nodes_ready, missing_nodes = node_classes_available(info.payload, required)
            else:
                missing_nodes = required
    options["_comfyui_required_nodes_available"] = nodes_ready
    options["_comfyui_missing_nodes"] = missing_nodes
    options["_comfyui_backend_ready"] = bool(health.success and workflow.ready and assets.ready and nodes_ready)

    _log_readiness(
        worker,
        health,
        assets.error,
        workflow.error,
        workflow.warning,
        missing_nodes,
        options["_comfyui_backend_ready"],
    )


def _auto_start_and_wait(worker, tools, options: dict, client: ComfyUIClient, *, initial_health):
    """Start ComfyUI safely and wait up to the configured deadline.

    Parallel converter workers share this lock. A waiting worker re-checks the
    API before launching, and a short cooldown suppresses duplicate portable
    ComfyUI consoles while the first launch is still settling.
    """
    with _COMFYUI_START_LOCK:
        # Another worker may have started ComfyUI while this worker waited.
        health = client.health()
        if health.success:
            return health

        launcher = _resolve_comfyui_launcher(tools, options)
        if launcher is None:
            configured = str(options.get("comfyui_start_file") or "").strip()
            detail = f": {configured}" if configured else ""
            worker.log(
                "⚠️ ComfyUI API nicht erreichbar und keine ausführbare Startdatei gefunden"
                f"{detail}. SDR→HDR fällt für betroffene Dateien sicher auf SDR zurück.",
                "warn",
            )
            return initial_health

        wait_seconds = _bounded_int(options.get("comfyui_start_wait_seconds"), 30, 5, 180)
        options["_comfyui_start_file_effective"] = str(launcher)
        launcher_key = str(launcher).casefold()
        last_attempt = _COMFYUI_START_ATTEMPTS.get(launcher_key, 0.0)
        now = time.monotonic()
        if last_attempt and now - last_attempt < 60.0:
            worker.log(
                "⚠️ ComfyUI wurde vor weniger als 60 s bereits automatisch gestartet; "
                "kein zweiter Launcher wird parallel geöffnet.",
                "warn",
            )
            return health
        _COMFYUI_START_ATTEMPTS[launcher_key] = now
        worker.log(
            f"🚀 ComfyUI API nicht erreichbar. Starte '{launcher.name}' und warte bis zu {wait_seconds} s auf die API …",
            "info",
        )
        try:
            _launch_file(launcher)
        except Exception as exc:
            worker.log(f"⚠️ ComfyUI konnte nicht gestartet werden: {exc}", "warn")
            return initial_health

        deadline = time.monotonic() + wait_seconds
        last_health = initial_health
        while time.monotonic() < deadline:
            if bool(getattr(worker, "abort_requested", False)):
                worker.log("⚠️ ComfyUI-Startwartezeit wegen Abbruch beendet.", "warn")
                return last_health
            # Polling instead of a blind 30-second sleep keeps fast launches fast
            # while preserving the requested 30-second maximum startup window.
            time.sleep(1.0)
            last_health = client.health()
            if last_health.success:
                elapsed = max(1, wait_seconds - int(max(0.0, deadline - time.monotonic())))
                worker.log(f"✅ ComfyUI API nach ca. {elapsed} s erreichbar.", "success")
                return last_health

        worker.log(
            f"⚠️ ComfyUI wurde gestartet, die API ist nach {wait_seconds} s aber weiterhin nicht erreichbar.",
            "warn",
        )
        return last_health


def _resolve_comfyui_launcher(tools, options: dict) -> Path | None:
    explicit = str(options.get("comfyui_start_file") or "").strip()
    if explicit:
        candidate = Path(explicit).expanduser()
        return candidate.resolve() if candidate.is_file() and _supported_launcher(candidate) else None

    marker_text = str(getattr(tools, "comfyui", "") or "").strip()
    if not marker_text:
        return None
    marker = Path(marker_text).expanduser()
    try:
        if marker.is_file() and marker.suffix.lower() == ".exe":
            return marker.resolve()
    except OSError:
        return None

    # Portable layout: <root>/ComfyUI/main.py + <root>/run_nvidia_gpu.bat.
    roots: list[Path] = []
    current = marker.parent if marker.suffix else marker
    for _ in range(3):
        if current not in roots:
            roots.append(current)
        if current.parent == current:
            break
        current = current.parent
    for root in roots:
        for name in _COMMON_PORTABLE_LAUNCHERS:
            candidate = root / name
            try:
                if candidate.is_file():
                    return candidate.resolve()
            except OSError:
                continue
    return None


def _supported_launcher(path: Path) -> bool:
    return path.suffix.lower() in {".bat", ".cmd", ".exe"}


def _launch_file(path: Path) -> None:
    suffix = path.suffix.lower()
    cwd = str(path.parent)
    creationflags = 0
    if os.name == "nt":
        creationflags = int(getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)) | int(
            getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
        )
    if suffix in {".bat", ".cmd"}:
        if os.name != "nt":
            raise RuntimeError(".bat/.cmd-Startdateien werden nur unter Windows unterstützt.")
        comspec = os.environ.get("COMSPEC") or "cmd.exe"
        command = [comspec, "/d", "/s", "/c", "call", str(path)]
    elif suffix == ".exe":
        command = [str(path)]
    else:
        raise RuntimeError("Unterstützt werden .bat, .cmd und .exe als ComfyUI-Startdatei.")

    subprocess.Popen(
        command,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        stdout=None,
        stderr=None,
        close_fds=True,
        creationflags=creationflags,
    )


def _bounded_int(value, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(maximum, parsed))


def _log_readiness(
    worker,
    health,
    asset_error: str,
    workflow_error: str,
    workflow_warning: str,
    missing_nodes: tuple[str, ...],
    ready: bool,
) -> None:
    if not health.success:
        worker.log(
            "⚠️ SDR→HDR Backend: ComfyUI gewählt, aber die lokale API ist nicht erreichbar; "
            "bestehende Standardpfade bleiben unverändert.", "warn",
        )
        return
    device = f" auf {health.device}" if health.device else ""
    version = f" {health.version}" if health.version else ""
    if asset_error:
        worker.log(f"⚠️ ComfyUI{version}{device}: {asset_error}", "warn")
        return
    if missing_nodes:
        worker.log(
            f"⚠️ ComfyUI{version}{device}: DragonTools-HDRTVDM-Nodes fehlen: {', '.join(missing_nodes)}", "warn",
        )
        return
    if workflow_error:
        worker.log(f"⚠️ ComfyUI{version}{device}: Workflow ungültig: {workflow_error}", "warn")
        return
    if workflow_warning:
        worker.log(f"⚠️ ComfyUI{version}{device}: {workflow_warning}", "warn")
    worker.log(
        f"🧪 ComfyUI{version}{device}: HDRTVDM-Modell, Streaming-Video-Node und Workflow sind ausführbar."
        if ready else f"🧪 ComfyUI{version}{device}: Backend vorbereitet.",
        "info",
    )


__all__ = [
    "configure_comfyui_runtime",
    "_resolve_comfyui_launcher",
    "_supported_launcher",
]
