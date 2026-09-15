# -*- coding: utf-8 -*-
"""Compatibility facade and orchestrator for expected media-contract checks."""
from __future__ import annotations

from .media_contract_types import ExpectedMediaContract
from .workflow_engine import WorkflowVerifyResult
from .output_contract_video import video_bit_depth, verify_video_contract
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
    messages = verify_video_contract(contract, video_streams)

    audio_messages = compare_audio_tracks(contract, audio_streams)
    if audio_messages:
        result.audio_ok = False
        messages.extend(audio_messages)

    subtitle_messages = compare_subtitle_tracks(contract, subtitle_streams)
    if subtitle_messages:
        result.subtitle_ok = False
        messages.extend(subtitle_messages)

    messages.extend(
        verify_auxiliary_stream_contract(
            contract,
            attachment_streams,
            data_streams,
        )
    )

    metadata_messages = verify_dynamic_metadata_contract(result, contract)
    if metadata_messages:
        result.metadata_ok = False
        messages.extend(metadata_messages)

    result.contract_ok = not messages
    result.messages.extend(messages)


__all__ = [
    "apply_contract",
    "video_bit_depth",
    "compare_audio_tracks",
    "compare_subtitle_tracks",
]
