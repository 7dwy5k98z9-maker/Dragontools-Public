# -*- coding: utf-8 -*-
"""Executable full-file ComfyUI/HDRTVDM SDR->HDR video backend.

DragonTools owns orchestration, audio/subtitle muxing and final validation.  The
ComfyUI workflow receives only the video path plus the exact DragonTools video
filter/encoder arguments and produces a video-only HDR10/PQ intermediate.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Any

from ..core.comfyui_hdr_models import HDRTVDM_PROFILE, ComfyUIWorkflowSelection, resolve_comfyui_workflow
from ..core.comfyui_workflow import render_comfyui_workflow
from .comfyui_client import ComfyUIClient


@dataclass(frozen=True, slots=True)
class ComfyUIVideoResult:
    success: bool
    output_path: str = ""
    prompt_id: str = ""
    frames: int = 0
    elapsed_s: float = 0.0
    peak_vram_bytes: int | None = None
    error: str = ""
    message: str = ""


class ComfyUIHDRVideoService:
    """Run one complete CFR source through the configured ComfyUI workflow."""

    def __init__(self, *, tools, worker=None, log=None) -> None:
        self._tools = tools
        self._worker = worker
        self._log = log or (lambda *_args, **_kwargs: None)

    def render(
        self,
        *,
        input_path: str,
        output_path: str,
        media_info,
        encoder_options: dict[str, Any],
        decode_args: list[str],
        encode_args: list[str],
        hdr_output_args: list[str],
        manifest_path: str,
    ) -> ComfyUIVideoResult:
        fps = _source_cfr(media_info)
        if fps is None:
            return ComfyUIVideoResult(
                False, error="UNSUPPORTED_TIMING",
                message="ComfyUI/HDRTVDM benötigt aktuell eine eindeutig erkannte CFR-Quelle.",
            )

        profile = str(encoder_options.get("_comfyui_model_profile") or HDRTVDM_PROFILE).strip().lower()
        workflow_selection = self._workflow(encoder_options, profile)
        if not workflow_selection.ready or workflow_selection.workflow is None:
            return ComfyUIVideoResult(
                False, error="WORKFLOW_MISSING",
                message=workflow_selection.error or "ComfyUI API-Workflow fehlt.",
            )
        if workflow_selection.warning:
            self._log(f"⚠️ ComfyUI/HDRTVDM: {workflow_selection.warning}", "warn")
        workflow = workflow_selection.workflow

        model_root = str(encoder_options.get("_comfyui_model_repository") or encoder_options.get("comfyui_model_root") or "")
        checkpoint = str(encoder_options.get("_comfyui_model_checkpoint") or encoder_options.get("comfyui_checkpoint") or "")
        expected_frames = int(getattr(getattr(media_info, "primary_video", None), "frame_count", 0) or 0)
        values = {
            "INPUT_VIDEO": str(input_path),
            "OUTPUT_VIDEO": str(output_path),
            "FFMPEG": str(self._tools.ffmpeg),
            "MODEL_ROOT": model_root,
            "CHECKPOINT": checkpoint,
            "DECODE_ARGS_JSON": json.dumps([str(item) for item in decode_args], ensure_ascii=False),
            "ENCODE_ARGS_JSON": json.dumps([str(item) for item in encode_args], ensure_ascii=False),
            "HDR_ARGS_JSON": json.dumps([str(item) for item in hdr_output_args], ensure_ascii=False),
            "FPS_NUM": fps.numerator,
            "FPS_DEN": fps.denominator,
            "BATCH_SIZE": 1,
            "EXPECTED_FRAMES": expected_frames,
            "MANIFEST_PATH": str(manifest_path),
        }
        try:
            rendered = render_comfyui_workflow(workflow, values)
        except Exception as exc:
            return ComfyUIVideoResult(False, error="WORKFLOW_RENDER_FAILED", message=str(exc))

        client = ComfyUIClient(str(encoder_options.get("comfyui_base_url") or "http://127.0.0.1:8188"), timeout_s=5.0)
        queued = client.queue_workflow(rendered)
        if not queued.success:
            return ComfyUIVideoResult(False, error=queued.error or "QUEUE_FAILED", message=queued.message)

        self._log(
            f"🧠 ComfyUI/HDRTVDM: Voll-Datei-Job gestartet ({fps.numerator}/{fps.denominator} fps, Prompt {queued.prompt_id}).",
            "info",
        )
        waited = self._wait_for_completion(client, queued.prompt_id, Path(manifest_path), input_path)
        if not waited.success:
            return waited

        out = Path(output_path)
        if not out.is_file() or out.stat().st_size <= 0:
            return ComfyUIVideoResult(
                False, prompt_id=queued.prompt_id, error="OUTPUT_MISSING",
                message="ComfyUI meldete Erfolg, aber der HDR-Videostream fehlt.",
            )
        manifest = _read_manifest(Path(manifest_path))
        if manifest.get("success") is not True:
            return ComfyUIVideoResult(
                False, prompt_id=queued.prompt_id, error=str(manifest.get("error") or "MANIFEST_INVALID"),
                message=str(manifest.get("message") or "HDRTVDM-Manifest meldet keinen Erfolg."),
            )
        frames = _safe_int(manifest.get("frames"), 0)
        if frames <= 0:
            return ComfyUIVideoResult(
                False, prompt_id=queued.prompt_id, error="NO_FRAMES",
                message="HDRTVDM hat keine Frames ausgegeben.",
            )
        if expected_frames > 0 and frames != expected_frames:
            try:
                out.unlink(missing_ok=True)
            except OSError:
                pass
            return ComfyUIVideoResult(
                False, prompt_id=queued.prompt_id, error="FRAME_COUNT_MISMATCH",
                message=f"HDRTVDM-Framezahl weicht ab: Quelle={expected_frames}, Ausgabe={frames}.",
            )
        return ComfyUIVideoResult(
            True,
            output_path=str(out),
            prompt_id=queued.prompt_id,
            frames=frames,
            elapsed_s=_safe_float(manifest.get("elapsed_s"), 0.0),
            peak_vram_bytes=_safe_int_or_none(manifest.get("peak_vram_bytes")),
            message="ComfyUI/HDRTVDM abgeschlossen.",
        )

    def _workflow(self, options: dict[str, Any], profile: str) -> ComfyUIWorkflowSelection:
        return resolve_comfyui_workflow(
            profile,
            workflow_path=options.get("comfyui_workflow_path"),
        )

    def _wait_for_completion(
        self,
        client: ComfyUIClient,
        prompt_id: str,
        manifest_path: Path,
        input_path: str,
    ) -> ComfyUIVideoResult:
        last_frames = -1
        while True:
            if _aborted(self._worker):
                cancelled = client.cancel(prompt_id)
                detail = cancelled.message or cancelled.error or "Abbruch angefordert"
                return ComfyUIVideoResult(False, prompt_id=prompt_id, error="ABORTED", message=detail)

            history = client.history(prompt_id)
            if not history.success:
                return ComfyUIVideoResult(False, prompt_id=prompt_id, error=history.error, message=history.message)
            entry = history.payload.get(prompt_id)
            if isinstance(entry, dict):
                status = entry.get("status") if isinstance(entry.get("status"), dict) else {}
                if status.get("completed") is True:
                    status_text = str(status.get("status_str") or "").strip().lower()
                    if status_text and status_text not in {"success", "completed"}:
                        return ComfyUIVideoResult(
                            False, prompt_id=prompt_id, error="COMFYUI_JOB_FAILED",
                            message=_history_error_message(status) or f"ComfyUI-Status: {status_text}",
                        )
                    return ComfyUIVideoResult(True, prompt_id=prompt_id)

            manifest = _read_manifest(manifest_path, allow_missing=True)
            frames = _safe_int(manifest.get("frames"), 0)
            if frames > last_frames:
                last_frames = frames
                expected = _safe_int(manifest.get("expected_frames"), 0)
                if expected > 0:
                    pct = min(99, int(frames * 100 / expected))
                    self._log(f"🧠 ComfyUI/HDRTVDM: {frames}/{expected} Frames ({pct}%).", "info")
                elif frames > 0 and frames % 100 == 0:
                    self._log(f"🧠 ComfyUI/HDRTVDM: {frames} Frames verarbeitet.", "info")
            time.sleep(0.75)


def _source_cfr(media_info) -> Fraction | None:
    video = getattr(media_info, "primary_video", None)
    if video is None:
        return None
    mode = str(getattr(video, "frame_rate_mode", "") or "").strip().upper()
    if mode != "CFR":
        return None
    raw = str(getattr(video, "frame_rate", "") or "").strip().replace(",", ".")
    if not raw:
        return None
    try:
        fps = Fraction(raw) if "/" in raw else Fraction(raw).limit_denominator(1001)
    except (ValueError, ZeroDivisionError):
        return None
    return fps if fps > 0 else None


def _read_manifest(path: Path, *, allow_missing: bool = False) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, dict) else {}
    except (OSError, json.JSONDecodeError):
        if allow_missing:
            return {}
        return {}


def _history_error_message(status: dict[str, Any]) -> str:
    messages = status.get("messages")
    if not isinstance(messages, list):
        return ""
    for item in reversed(messages):
        if isinstance(item, (list, tuple)) and len(item) >= 2 and str(item[0]).lower() in {"execution_error", "error"}:
            detail = item[1]
            if isinstance(detail, dict):
                return str(detail.get("exception_message") or detail.get("message") or detail)
            return str(detail)
    return ""


def _aborted(worker) -> bool:
    return bool(getattr(worker, "abort_requested", False)) if worker is not None else False


def _safe_int(value: object, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_int_or_none(value: object) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _safe_float(value: object, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


__all__ = ["ComfyUIHDRVideoService", "ComfyUIVideoResult"]
