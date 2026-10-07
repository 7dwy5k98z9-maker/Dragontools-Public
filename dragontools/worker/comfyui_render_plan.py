"""Prepare an isolated, explicit full-video contract before touching job files."""
from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from ..core.comfyui_hdr_models import HDRTVDM_PROFILE
from ..core.comfyui_timing import source_cfr
from ..core.comfyui_workflow import render_comfyui_workflow
from ..core.media_stream_selection import primary_ffmpeg_video_index, pin_primary_video_selector
from ..core.sdr_hdr_enhancement import source_is_supported_sdr_bt709
from ..core.strict_numbers import nonnegative_integer
from .comfyui_job_monitor import ComfyUIVideoResult
from .comfyui_video_contract import validate_job_paths
from .frame_count_evidence import temporal_mapping_for_filters
from .log_dispatch import dispatch_log


@dataclass(frozen=True, slots=True)
class ComfyUIRenderPlan:
    fps: Fraction
    source_index: int
    expected_frames: int
    workflow: dict
    options: dict
    output: Path
    manifest: Path
    encode_args: tuple[str, ...]


def prepare_render_plan(*, tools, log, resolve_workflow, input_path, output_path, media_info,
    encoder_options, decode_args, encode_args, hdr_output_args, manifest_path):
    try:
        validate_job_paths(input_path, output_path, manifest_path)
    except ValueError as exc:
        return ComfyUIVideoResult(False, error='PATH_COLLISION', message=str(exc))
    fps = source_cfr(media_info)
    if fps is None or temporal_mapping_for_filters(decode_args) != 'preserved':
        return ComfyUIVideoResult(False, error='UNSUPPORTED_TIMING', message='ComfyUI benötigt eine gültige CFR-Quelle ohne zeitverändernde Bildfilter.')
    supported, reason = source_is_supported_sdr_bt709(media_info)
    if not supported:
        return ComfyUIVideoResult(False, error='UNSUPPORTED_SOURCE', message=reason)
    source_index = primary_ffmpeg_video_index(media_info)
    if source_index is None:
        return ComfyUIVideoResult(False, error='INVALID_VIDEO_SELECTION', message='Kein gültiger globaler Quellvideoindex.')
    selected_args = pin_primary_video_selector(list(decode_args), source_index)
    maps = [str(selected_args[pos + 1]) for pos, item in enumerate(selected_args[:-1]) if item == '-map']
    if len(maps) != 1 or maps[0] not in {f'0:{source_index}', '[vout]'}:
        return ComfyUIVideoResult(False, error='INVALID_VIDEO_SELECTION', message='Decoder-Mapping entspricht nicht dem analysierten Primärvideo.')
    if maps[0] == '[vout]' and f'[0:{source_index}]' not in ' '.join(str(arg) for arg in selected_args):
        return ComfyUIVideoResult(False, error='INVALID_VIDEO_SELECTION', message='Komplexes Mapping enthält nicht das analysierte Primärvideo.')
    options = deepcopy(encoder_options)
    profile = str(options.get('comfyui_model_profile') or options.get('_comfyui_model_profile') or HDRTVDM_PROFILE).strip().lower()
    selection = resolve_workflow(options, profile)
    if not selection.ready or selection.workflow is None:
        return ComfyUIVideoResult(False, error='WORKFLOW_MISSING', message=selection.error or 'ComfyUI API-Workflow fehlt.')
    if selection.warning:
        dispatch_log(log, f'⚠️ ComfyUI/HDRTVDM: {selection.warning}', 'warn')
    try:
        expected = nonnegative_integer(getattr(media_info.primary_video, 'frame_count', 0) or 0)
        values = {
            'INPUT_VIDEO': str(input_path), 'OUTPUT_VIDEO': str(output_path), 'FFMPEG': str(tools.ffmpeg),
            'MODEL_ROOT': str(options.get('_comfyui_model_repository') or options.get('comfyui_model_root') or ''),
            'CHECKPOINT': str(options.get('_comfyui_model_checkpoint') or options.get('comfyui_checkpoint') or ''),
            'DECODE_ARGS_JSON': json.dumps(selected_args, ensure_ascii=False),
            'ENCODE_ARGS_JSON': json.dumps(list(encode_args), ensure_ascii=False),
            'HDR_ARGS_JSON': json.dumps(list(hdr_output_args), ensure_ascii=False),
            'FPS_NUM': fps.numerator, 'FPS_DEN': fps.denominator, 'BATCH_SIZE': 1,
            'EXPECTED_FRAMES': expected, 'MANIFEST_PATH': str(manifest_path),
        }
        rendered = render_comfyui_workflow(selection.workflow, values)
    except (ValueError, TypeError, OverflowError) as exc:
        return ComfyUIVideoResult(False, error='WORKFLOW_RENDER_FAILED', message=str(exc))
    return ComfyUIRenderPlan(fps, source_index, expected, rendered, options, Path(output_path), Path(manifest_path), tuple(encode_args))
