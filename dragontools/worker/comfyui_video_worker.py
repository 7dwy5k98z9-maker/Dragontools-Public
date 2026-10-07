# -*- coding: utf-8 -*-
"""Compatibility facade for explicit ComfyUI planning, monitoring and verification."""
from __future__ import annotations

import time  # Kept for existing deterministic clock adapters.
from pathlib import Path

from ..core.comfyui_hdr_models import resolve_comfyui_workflow
from ..core.comfyui_timing import source_cfr as _source_cfr
from .comfyui_client import ComfyUIClient
from .comfyui_job_monitor import (
    ComfyUIVideoResult, wait_for_completion, read_manifest as _read_manifest,
    safe_int as _safe_int, safe_float as _safe_float,
    history_error_message as _history_error_message,
)
from .comfyui_render_plan import prepare_render_plan, ComfyUIRenderPlan
from .comfyui_video_contract import verify_comfyui_video
from .log_dispatch import dispatch_log

DEFAULT_COMFYUI_INACTIVITY_TIMEOUT_S = 900.0


class ComfyUIHDRVideoService:
    def __init__(self, *, tools, worker=None, log=None):
        self._tools, self._worker, self._log = tools, worker, log

    def render(self, *, input_path, output_path, media_info, encoder_options,
        decode_args, encode_args, hdr_output_args, manifest_path):
        plan = prepare_render_plan(tools=self._tools, log=self._log, resolve_workflow=self._workflow,
            input_path=input_path, output_path=output_path, media_info=media_info,
            encoder_options=encoder_options, decode_args=decode_args, encode_args=encode_args,
            hdr_output_args=hdr_output_args, manifest_path=manifest_path)
        if not isinstance(plan, ComfyUIRenderPlan):
            return plan
        cleanup_error = _remove_stale_job_artifacts(plan.output, plan.manifest)
        if cleanup_error:
            return ComfyUIVideoResult(False, error='STALE_ARTIFACT_CLEANUP_FAILED', message=cleanup_error)
        client = ComfyUIClient(str(plan.options.get('comfyui_base_url') or 'http://127.0.0.1:8188'), timeout_s=5.0)
        queued = client.queue_workflow(plan.workflow)
        if not queued.success:
            # A lost response can follow a successfully queued remote prompt.
            # Preserve this unique tree and signal the bridge before returning.
            if queued.error == 'QUEUE_FAILED':
                try:
                    Path(str(plan.manifest) + '.cancel').write_text('queue response lost', encoding='utf-8')
                except OSError as exc:
                    dispatch_log(self._log, f'ComfyUI: lokale Abbruchdatei fehlgeschlagen: {exc}', 'warn')
            return ComfyUIVideoResult(False, error=queued.error or 'QUEUE_FAILED', message=queued.message,
                preserve_artifacts=queued.error == 'QUEUE_FAILED')
        dispatch_log(self._log, f'🧠 ComfyUI/HDRTVDM: Voll-Datei-Job gestartet ({plan.fps} fps, Prompt {queued.prompt_id}).', 'info')
        timeout = _safe_float(plan.options.get('comfyui_inactivity_timeout_s'), DEFAULT_COMFYUI_INACTIVITY_TIMEOUT_S)
        waited = self._wait_for_completion(client, queued.prompt_id, plan.manifest, input_path, inactivity_timeout_s=max(30.0, timeout))
        if not waited.success:
            if not waited.preserve_artifacts:
                _remove_failed_output(plan.output)
            return waited
        return self._verified_result(plan, queued.prompt_id, input_path)

    def _verified_result(self, plan, prompt_id, input_path):
        try:
            if not plan.output.is_file() or plan.output.stat().st_size <= 0:
                return ComfyUIVideoResult(False, prompt_id=prompt_id, error='OUTPUT_MISSING', message='HDR-Videostream fehlt.')
        except OSError as exc:
            return ComfyUIVideoResult(False, prompt_id=prompt_id, error='OUTPUT_MISSING', message=str(exc))
        manifest = _read_manifest(plan.manifest)
        if manifest.get('success') is not True:
            return ComfyUIVideoResult(False, prompt_id=prompt_id, error=str(manifest.get('error') or 'MANIFEST_INVALID'),
                message=str(manifest.get('message') or 'HDRTVDM-Manifest meldet keinen Erfolg.'))
        frames = _safe_int(manifest.get('frames'), 0)
        if frames <= 0:
            return ComfyUIVideoResult(False, prompt_id=prompt_id, error='NO_FRAMES', message='HDRTVDM hat keine gültige Framezahl ausgegeben.')
        if plan.expected_frames > 0 and frames != plan.expected_frames:
            _remove_failed_output(plan.output)
            return ComfyUIVideoResult(False, prompt_id=prompt_id, error='FRAME_COUNT_MISMATCH',
                message=f'HDRTVDM-Framezahl weicht ab: Quelle={plan.expected_frames}, Ausgabe={frames}.')
        evidence = verify_comfyui_video(tools=self._tools, worker=self._worker, log=self._log,
            input_path=input_path, output_path=plan.output, source_index=plan.source_index,
            fps=plan.fps, frames=frames, encode_args=plan.encode_args)
        if not evidence.success:
            return ComfyUIVideoResult(False, prompt_id=prompt_id, error='OUTPUT_INVALID', message=evidence.message)
        return ComfyUIVideoResult(True, output_path=str(plan.output), prompt_id=prompt_id, frames=frames,
            elapsed_s=_safe_float(manifest.get('elapsed_s'), 0.0), peak_vram_bytes=_safe_int(manifest.get('peak_vram_bytes'), 0),
            video_offset_s=evidence.video_offset_s, source_input_offset_s=getattr(evidence, 'source_input_offset_s', 0.0),
            source_audio_count=getattr(evidence, 'source_audio_count', 0), source_subtitle_count=getattr(evidence, 'source_subtitle_count', 0),
            message='ComfyUI/HDRTVDM abgeschlossen und Videostream geprüft.')

    def _workflow(self, options, profile):
        return resolve_comfyui_workflow(profile, workflow_path=options.get('comfyui_workflow_path'))

    def _wait_for_completion(self, client, prompt_id, manifest_path, input_path, *, inactivity_timeout_s=DEFAULT_COMFYUI_INACTIVITY_TIMEOUT_S):
        return wait_for_completion(client, prompt_id, manifest_path, input_path, worker=self._worker,
            log=self._log, inactivity_timeout_s=inactivity_timeout_s)


def _remove_stale_job_artifacts(output_path, manifest_path):
    for path in (output_path, manifest_path, Path(str(manifest_path) + '.cancel')):
        try: path.unlink(missing_ok=True)
        except OSError as exc: return f'Altes Job-Artefakt konnte nicht entfernt werden: {path} ({exc})'
    return ''


def _remove_failed_output(path):
    try: path.unlink(missing_ok=True)
    except OSError: pass


__all__ = ['ComfyUIHDRVideoService', 'ComfyUIVideoResult']
