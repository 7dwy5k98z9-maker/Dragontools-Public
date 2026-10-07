"""Track a single external prompt and retain its tree until termination is proven."""
from __future__ import annotations

import json
import math
import time
from dataclasses import dataclass
from pathlib import Path

from ..core.strict_numbers import nonnegative_integer
from .log_dispatch import dispatch_log


@dataclass(frozen=True, slots=True)
class ComfyUIVideoResult:
    success: bool
    output_path: str = ''
    prompt_id: str = ''
    frames: int = 0
    elapsed_s: float = 0.0
    peak_vram_bytes: int | None = None
    error: str = ''
    message: str = ''
    preserve_artifacts: bool = False
    video_offset_s: float = 0.0
    source_input_offset_s: float | None = None
    source_audio_count: int = 0
    source_subtitle_count: int = 0


def read_manifest(path, *, allow_missing=False):
    try:
        payload = json.loads(Path(path).read_text(encoding='utf-8'))
        return payload if isinstance(payload, dict) else {}
    except (OSError, ValueError):
        return {}


def safe_int(value, default):
    try: return nonnegative_integer(value)
    except ValueError: return default


def safe_float(value, default):
    try:
        parsed = float(value)
        return parsed if math.isfinite(parsed) and parsed >= 0 else default
    except (TypeError, ValueError, OverflowError):
        return default


def history_finished(payload, prompt_id):
    entry = payload.get(prompt_id)
    status = entry.get('status') if isinstance(entry, dict) else None
    return status if isinstance(status, dict) and status.get('completed') is True else None


def cancel_owned_job(client, prompt_id, manifest_path, error, message):
    # The job-specific sentinel also stops the bridge when the HTTP API is
    # unreachable or too old to implement the targeted cancellation endpoint.
    detail = ''
    try:
        Path(str(manifest_path) + '.cancel').write_text(prompt_id, encoding='utf-8')
    except OSError as exc:
        detail = f'Lokale Abbruchdatei konnte nicht geschrieben werden: {exc}'
    cancelled = client.cancel(prompt_id)
    terminal = client.history(prompt_id)
    stopped = terminal.success and history_finished(terminal.payload, prompt_id) is not None
    if not stopped:
        detail += ' Auftragende nicht bestätigt; temporäre Dateien bleiben erhalten.'
    if not cancelled.success:
        detail += ' ' + (cancelled.message or cancelled.error)
    return ComfyUIVideoResult(False, prompt_id=prompt_id, error=error,
        message=(message + ' ' + detail).strip(), preserve_artifacts=not stopped)


def wait_for_completion(client, prompt_id, manifest_path, input_path, *, worker, log, inactivity_timeout_s):
    last_frames, last_status = -1, ''
    last_activity = time.monotonic()
    while True:
        if bool(getattr(worker, 'abort_requested', False)):
            return cancel_owned_job(client, prompt_id, manifest_path, 'ABORTED', 'Abbruch angefordert.')
        history = client.history(prompt_id)
        if not history.success:
            return cancel_owned_job(client, prompt_id, manifest_path, history.error or 'HISTORY_FAILED', history.message or 'Historie nicht erreichbar.')
        entry = history.payload.get(prompt_id)
        status = entry.get('status') if isinstance(entry, dict) else None
        if isinstance(status, dict):
            text = str(status.get('status_str') or '').lower()
            if text and text != last_status:
                last_status, last_activity = text, time.monotonic()
            if status.get('completed') is True:
                success = text in {'success', 'completed'}
                return ComfyUIVideoResult(success, prompt_id=prompt_id, error='' if success else 'COMFYUI_JOB_FAILED', message=history_error_message(status))
        manifest = read_manifest(manifest_path)
        frames = safe_int(manifest.get('frames'), 0)
        if frames > last_frames:
            last_frames, last_activity = frames, time.monotonic()
            expected = safe_int(manifest.get('expected_frames'), 0)
            if expected > 0:
                dispatch_log(log, f'🧠 ComfyUI/HDRTVDM: {frames}/{expected} Frames ({min(99, frames * 100 // expected)}%).', 'info')
        idle = time.monotonic() - last_activity
        if idle >= max(30.0, inactivity_timeout_s):
            return cancel_owned_job(client, prompt_id, manifest_path, 'INACTIVITY_TIMEOUT', f'ComfyUI/HDRTVDM meldete {idle:.0f}s keinen Fortschritt für {input_path}.')
        time.sleep(0.75)


def history_error_message(status):
    messages = status.get('messages')
    if isinstance(messages, list):
        for item in reversed(messages):
            if isinstance(item, (list, tuple)) and len(item) >= 2 and str(item[0]).lower() in {'execution_error', 'error'}:
                detail = item[1]
                return str(detail.get('exception_message') or detail.get('message') or detail) if isinstance(detail, dict) else str(detail)
    return str(status.get('status_str') or '')
