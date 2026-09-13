from __future__ import annotations

from pathlib import Path

from .dv_pipeline_timeouts import timeout_mp4box as _TIMEOUT_MP4BOX, timeout_mkvmerge as _TIMEOUT_MKVMERGE


class DVFinalOutputService:
    def __init__(self, *, mp4box_muxer, mkv_muxer, log, verbose_log, assert_nonempty_file) -> None:
        self._mp4box_muxer = mp4box_muxer
        self._mkv_muxer = mkv_muxer
        self._log = log
        self._vlog = verbose_log
        self._assert_nonempty_file = assert_nonempty_file

    def mux(self, state, runner, *, verify_final_mux_metadata) -> bool:
        req, files = state.request, state.files
        container = str(getattr(req, "container", "mp4") or "mp4").lower()
        self._vlog(f"[TRACE][DV] before final {container} creation (video={files.injected.name}, audio_tracks={len(state.mux_audio_tracks)}, subtitle_tracks={len(state.mux_subtitle_tracks)})")
        ok, label = self._mux_container(container, state, runner)
        if not ok:
            self._log(f"❌ [DV][STEP 7/7] ERROR - {container.upper()}-Mux fehlgeschlagen.", "error")
            return False
        if not self._assert_nonempty_file(Path(req.output_path), label):
            return False
        return verify_final_mux_metadata(state, runner)

    def _mux_container(self, container: str, state, runner) -> tuple[bool, str]:
        req, files = state.request, state.files
        if container == "mkv":
            self._log("ℹ️  [DV][STEP 7/7] MKV-Mux (mkvmerge)", "info")
            run_mux = runner.adapter(timeout=_TIMEOUT_MKVMERGE(), label="STEP 7/7 MKV-Mux")
            ok = self._mkv_muxer.mux_final_output(run_mux, output_path=req.output_path, injected_hevc=files.injected,
                mux_tracks=state.mux_audio_tracks, subtitle_tracks=state.mux_subtitle_tracks)
            return ok, "STEP 7 MKV-Mux"
        self._log("ℹ️  [DV][STEP 7/7] MP4Box-Mux (streamingoptimiert)", "info")
        run_mux = runner.adapter(timeout=_TIMEOUT_MP4BOX(), label="STEP 7/7 MP4Box-Mux")
        ok = self._mp4box_muxer.mux_final_output(run_mux, output_path=req.output_path, injected_hevc=files.injected,
            mux_tracks=state.mux_audio_tracks, subtitle_tracks=state.mux_subtitle_tracks)
        return ok, "STEP 7 MP4Box-Mux"
