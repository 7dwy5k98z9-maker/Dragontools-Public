# -*- coding: utf-8 -*-
"""Compatibility facade and orchestrator for expected media-contract checks."""
from __future__ import annotations

from .media_contract_types import ExpectedMediaContract
from .workflow_engine import WorkflowVerifyResult
from .output_contract_video import evaluate_video_contract, video_bit_depth, verify_video_contract
from .output_contract_tracks import (
    compare_audio_tracks,
    compare_subtitle_tracks,
    verify_auxiliary_stream_contract,
)
from .output_contract_metadata import verify_dynamic_metadata_contract


def apply_contract(
    result: WorkflowVerifyResult,
    contract: ExpectedMediaContract,
    *,
    video_streams: list[dict],
    audio_streams: list[dict],
    subtitle_streams: list[dict],
    attachment_streams: list[dict] | None = None,
    data_streams: list[dict] | None = None,
) -> None:
    video_eval = evaluate_video_contract(contract, video_streams)
    messages = list(video_eval.errors)
    warnings = list(getattr(result, "warnings", None) or [])
    warnings.extend(video_eval.warnings)
    result.warnings = warnings
    result.expected_width = video_eval.expected_width
    result.expected_height = video_eval.expected_height
    result.actual_width = video_eval.actual_width
    result.actual_height = video_eval.actual_height
    result.geometry_max_delta = int(video_eval.geometry_max_delta or 0)
    result.geometry_severity = str(video_eval.geometry_severity or "exact")

    non_geometry_messages = list(video_eval.non_geometry_errors)

    audio_messages = compare_audio_tracks(contract, audio_streams)
    if audio_messages:
        result.audio_ok = False
        messages.extend(audio_messages)
        non_geometry_messages.extend(audio_messages)

    subtitle_messages = compare_subtitle_tracks(contract, subtitle_streams)
    if subtitle_messages:
        result.subtitle_ok = False
        messages.extend(subtitle_messages)
        non_geometry_messages.extend(subtitle_messages)

    auxiliary_messages = verify_auxiliary_stream_contract(
        contract, attachment_streams, data_streams
    )
    messages.extend(auxiliary_messages)
    non_geometry_messages.extend(auxiliary_messages)

    metadata_messages = verify_dynamic_metadata_contract(result, contract)
    if metadata_messages:
        result.metadata_ok = False
        messages.extend(metadata_messages)

    result.contract_non_geometry_ok = not non_geometry_messages
    result.contract_ok = not messages
    result.messages.extend(messages)


__all__ = [
    "apply_contract",
    "video_bit_depth",
    "compare_audio_tracks",
    "compare_subtitle_tracks",
]
