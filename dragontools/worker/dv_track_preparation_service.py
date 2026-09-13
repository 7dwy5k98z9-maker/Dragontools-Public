from __future__ import annotations

from .dv_pipeline_timeouts import timeout_audio as _TIMEOUT_AUDIO
from .dv_subtitle_mux_service import dv_subtitle_storage


class DVTrackPreparationService:
    def __init__(self, *, temp_state, audio_mux_service, subtitle_mux_service, subtitle_rules, log, verbose_log) -> None:
        self._temp_state = temp_state
        self._audio_mux_service = audio_mux_service
        self._subtitle_mux_service = subtitle_mux_service
        self._subtitle_rules = dict(subtitle_rules or {})
        self._log = log
        self._vlog = verbose_log

    def prepare_audio(self, state, runner) -> bool:
        req, files = state.request, state.files
        run_audio = runner.adapter(timeout=_TIMEOUT_AUDIO(), label="Audio-Extraktion")
        self._vlog("[TRACE][DV] before audio mux preparation")
        state.audio_tracks, state.mux_audio_tracks = self._audio_mux_service.resolve_audio_mux_inputs(
            input_path=req.input_path, enc_mkv=None, audio_mux_src=files.audio_mux_src,
            audio_args=req.audio_args, audio_input_args=req.audio_input_args, audio_meta=state.audio_meta,
            tmp_dir=files.root, run_fn=run_audio,
        )
        self._vlog(f"[TRACE][DV] after audio mux preparation (extracted={len(state.audio_tracks)}, muxable={len(state.mux_audio_tracks)})")
        expected, actual = len(state.audio_meta), len(state.mux_audio_tracks)
        if not expected or actual == expected:
            return True
        reason = f"Audio-Aufbereitung unvollständig: {actual} von {expected} geplanten Audiospuren sind muxbar"
        if not self._temp_state.failure_reason:
            self._temp_state.record_failure(reason=reason, stage="Audio-Aufbereitung")
        else:
            self._temp_state.failure_reason = reason + f"; Tool: {self._temp_state.failure_reason}"
            self._temp_state.failure_stage = "Audio-Aufbereitung"
        self._log(f"❌ [DV] {reason}.", "error")
        return False

    def prepare_subtitles(self, state, runner) -> bool:
        req = state.request
        state.mux_subtitle_tracks = []
        storage_mode = dv_subtitle_storage(getattr(req, "container", "mp4"), self._subtitle_rules)
        if storage_mode == "sidecar":
            return True
        if self._subtitle_mux_service is None:
            reason = "Untertitel-Aufbereitung für den DV-Zielcontainer ist nicht initialisiert"
            self._temp_state.record_failure(reason=reason, stage="Untertitel-Aufbereitung")
            self._log(f"❌ [DV] {reason}.", "error")
            return False
        files = state.files
        run_subtitle = runner.adapter(timeout=_TIMEOUT_AUDIO(), label="Untertitel-Extraktion")
        is_mkv = str(getattr(req, "container", "mp4") or "mp4").lower() == "mkv"
        prepare = self._subtitle_mux_service.prepare_internal_mkv_tracks if is_mkv else self._subtitle_mux_service.prepare_internal_mp4_tracks
        ok, tracks = prepare(input_path=req.input_path, media_info=req.media_info, file_override=req.override, tmp_dir=files.root, run_fn=run_subtitle)
        state.mux_subtitle_tracks = list(tracks)
        if ok:
            return True
        reason = "Untertitel-Aufbereitung für DV-MKV fehlgeschlagen" if is_mkv else "Untertitel-Aufbereitung für DV-MP4 fehlgeschlagen"
        self._temp_state.record_failure(reason=reason, stage="Untertitel-Aufbereitung")
        return False
