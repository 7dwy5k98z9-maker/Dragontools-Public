# -*- coding: utf-8 -*-
from __future__ import annotations

from typing import Callable

from .dv_final_metadata_verifier import DVFinalMetadataVerifier
from .dv_final_output_service import DVFinalOutputService
from .dv_track_preparation_service import DVTrackPreparationService


class DVFinalMuxService:
    """Compatibility facade for track preparation, final mux and metadata verification."""

    def __init__(self, *, tools, temp_state, audio_mux_service, mp4box_muxer, mkv_muxer, rpu_service,
                 hdr10plus_service, subtitle_mux_service, subtitle_rules: dict | None,
                 log: Callable[[str, str], None], verbose_log: Callable[[str], None], assert_nonempty_file: Callable) -> None:
        self._track_preparation = DVTrackPreparationService(
            temp_state=temp_state, audio_mux_service=audio_mux_service, subtitle_mux_service=subtitle_mux_service,
            subtitle_rules=subtitle_rules, log=log, verbose_log=verbose_log,
        )
        self._output = DVFinalOutputService(
            mp4box_muxer=mp4box_muxer, mkv_muxer=mkv_muxer, log=log,
            verbose_log=verbose_log, assert_nonempty_file=assert_nonempty_file,
        )
        self._metadata = DVFinalMetadataVerifier(
            tools=tools, temp_state=temp_state, rpu_service=rpu_service, hdr10plus_service=hdr10plus_service,
            log=log, verbose_log=verbose_log, assert_nonempty_file=assert_nonempty_file,
        )

    def prepare_audio(self, state, runner) -> bool:
        return self._track_preparation.prepare_audio(state, runner)

    def prepare_subtitles(self, state, runner) -> bool:
        return self._track_preparation.prepare_subtitles(state, runner)

    def mux_final_output(self, state, runner, *, verify_final_mux_metadata) -> bool:
        return self._output.mux(state, runner, verify_final_mux_metadata=verify_final_mux_metadata)

    def verify_final_mux_metadata(self, state, runner, *, inspect_dynamic_hdr, verify_fallback) -> bool:
        return self._metadata.verify(state, runner, inspect_dynamic_hdr=inspect_dynamic_hdr, verify_fallback=verify_fallback)

    def verify_final_mux_metadata_fallback(self, state, runner, *, verify_dv: bool, verify_hdr10plus: bool, sha256_file) -> bool:
        return self._metadata.verify_fallback(state, runner, verify_dv=verify_dv, verify_hdr10plus=verify_hdr10plus, sha256_file=sha256_file)
