# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .dv_command_runner import DVCommandRunner
from .dv_pipeline_context import DVPipelineState
from .dv_pipeline_timeouts import (
    timeout_audio as _TIMEOUT_AUDIO,
    timeout_hevc_extract as _TIMEOUT_HEVC_EXTRACT,
    timeout_mp4box as _TIMEOUT_MP4BOX,
    timeout_mkvmerge as _TIMEOUT_MKVMERGE,
    timeout_rpu_extract as _TIMEOUT_RPU_EXTRACT,
)
from .dv_subtitle_mux_service import dv_subtitle_storage


class DVFinalMuxService:
    """Qt-freie Audio-/Untertitelaufbereitung, Final-Mux und Metadatenprüfung."""

    def __init__(
        self,
        *,
        tools,
        temp_state,
        audio_mux_service,
        mp4box_muxer,
        mkv_muxer,
        rpu_service,
        hdr10plus_service,
        subtitle_mux_service,
        subtitle_rules: dict | None,
        log: Callable[[str, str], None],
        verbose_log: Callable[[str], None],
        assert_nonempty_file: Callable[[Path, str], bool],
    ) -> None:
        self._tools = tools
        self._temp_state = temp_state
        self._audio_mux_service = audio_mux_service
        self._mp4box_muxer = mp4box_muxer
        self._mkv_muxer = mkv_muxer
        self._rpu_service = rpu_service
        self._hdr10plus_service = hdr10plus_service
        self._subtitle_mux_service = subtitle_mux_service
        self._subtitle_rules = dict(subtitle_rules or {})
        self._log = log
        self._vlog = verbose_log
        self._assert_nonempty_file = assert_nonempty_file

    def prepare_audio(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        req, files = state.request, state.files
        run_audio = runner.adapter(timeout=_TIMEOUT_AUDIO(), label="Audio-Extraktion")
        self._vlog("[TRACE][DV] before audio mux preparation")
        state.audio_tracks, state.mux_audio_tracks = self._audio_mux_service.resolve_audio_mux_inputs(
            input_path=req.input_path,
            enc_mkv=None,
            audio_mux_src=files.audio_mux_src,
            audio_args=req.audio_args,
            audio_input_args=req.audio_input_args,
            audio_meta=state.audio_meta,
            tmp_dir=files.root,
            run_fn=run_audio,
        )
        self._vlog(
            f"[TRACE][DV] after audio mux preparation "
            f"(extracted={len(state.audio_tracks)}, muxable={len(state.mux_audio_tracks)})"
        )
        expected = len(state.audio_meta)
        actual = len(state.mux_audio_tracks)
        if expected and actual != expected:
            reason = (
                "Audio-Aufbereitung unvollständig: "
                f"{actual} von {expected} geplanten Audiospuren sind muxbar"
            )
            if not self._temp_state.failure_reason:
                self._temp_state.record_failure(reason=reason, stage="Audio-Aufbereitung")
            else:
                self._temp_state.failure_reason = reason + f"; Tool: {self._temp_state.failure_reason}"
                self._temp_state.failure_stage = "Audio-Aufbereitung"
            self._log(f"❌ [DV] {reason}.", "error")
            return False
        return True

    def prepare_subtitles(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        req = state.request
        state.mux_subtitle_tracks = []
        storage_mode = dv_subtitle_storage(
            getattr(req, "container", "mp4"),
            self._subtitle_rules,
        )
        if storage_mode == "sidecar":
            return True
        if self._subtitle_mux_service is None:
            reason = "Untertitel-Aufbereitung für den DV-Zielcontainer ist nicht initialisiert"
            self._temp_state.record_failure(reason=reason, stage="Untertitel-Aufbereitung")
            self._log(f"❌ [DV] {reason}.", "error")
            return False

        files = state.files
        run_subtitle = runner.adapter(timeout=_TIMEOUT_AUDIO(), label="Untertitel-Extraktion")
        if str(getattr(req, "container", "mp4") or "mp4").lower() == "mkv":
            ok, tracks = self._subtitle_mux_service.prepare_internal_mkv_tracks(
                input_path=req.input_path,
                media_info=req.media_info,
                file_override=req.override,
                tmp_dir=files.root,
                run_fn=run_subtitle,
            )
            failure_reason = "Untertitel-Aufbereitung für DV-MKV fehlgeschlagen"
        else:
            ok, tracks = self._subtitle_mux_service.prepare_internal_mp4_tracks(
                input_path=req.input_path,
                media_info=req.media_info,
                file_override=req.override,
                tmp_dir=files.root,
                run_fn=run_subtitle,
            )
            failure_reason = "Untertitel-Aufbereitung für DV-MP4 fehlgeschlagen"
        state.mux_subtitle_tracks = list(tracks)
        if not ok:
            self._temp_state.record_failure(reason=failure_reason, stage="Untertitel-Aufbereitung")
            return False
        return True

    def mux_final_output(
        self,
        state: DVPipelineState,
        runner: DVCommandRunner,
        *,
        verify_final_mux_metadata: Callable[[DVPipelineState, DVCommandRunner], bool],
    ) -> bool:
        req, files = state.request, state.files
        container = str(getattr(req, "container", "mp4") or "mp4").lower()
        self._vlog(
            f"[TRACE][DV] before final {container} creation "
            f"(video={files.injected.name}, audio_tracks={len(state.mux_audio_tracks)}, "
            f"subtitle_tracks={len(state.mux_subtitle_tracks)})"
        )
        if container == "mkv":
            self._log("ℹ️  [DV][STEP 7/7] MKV-Mux (mkvmerge)", "info")
            run_mux = runner.adapter(timeout=_TIMEOUT_MKVMERGE(), label="STEP 7/7 MKV-Mux")
            ok = self._mkv_muxer.mux_final_output(
                run_mux,
                output_path=req.output_path,
                injected_hevc=files.injected,
                mux_tracks=state.mux_audio_tracks,
                subtitle_tracks=state.mux_subtitle_tracks,
            )
            label = "STEP 7 MKV-Mux"
        else:
            self._log("ℹ️  [DV][STEP 7/7] MP4Box-Mux (streamingoptimiert)", "info")
            run_mux = runner.adapter(timeout=_TIMEOUT_MP4BOX(), label="STEP 7/7 MP4Box-Mux")
            ok = self._mp4box_muxer.mux_final_output(
                run_mux,
                output_path=req.output_path,
                injected_hevc=files.injected,
                mux_tracks=state.mux_audio_tracks,
                subtitle_tracks=state.mux_subtitle_tracks,
            )
            label = "STEP 7 MP4Box-Mux"
        if not ok:
            self._log(f"❌ [DV][STEP 7/7] ERROR - {container.upper()}-Mux fehlgeschlagen.", "error")
            return False
        if not self._assert_nonempty_file(Path(req.output_path), label):
            return False
        return verify_final_mux_metadata(state, runner)

    def verify_final_mux_metadata(
        self,
        state: DVPipelineState,
        runner: DVCommandRunner,
        *,
        inspect_dynamic_hdr: Callable,
        verify_fallback: Callable[..., bool],
    ) -> bool:
        """Prüft den fertigen Zielcontainer primär mit MediaInfo, Bitstream als Fallback."""
        req = state.request
        self._vlog("[DV][VERIFY] Finale Datei mit MediaInfo prüfen")
        inspection = inspect_dynamic_hdr(req.output_path, self._tools)

        require_hdr10plus = bool(req.preserve_dv_hdr10plus_combo)
        # Bei physischem Video-Crop genügt "DV vorhanden" nicht: Die finale
        # Containerdatei muss exakt dieselbe, bereits L5-normalisierte RPU wie
        # der injizierte HEVC-Stream enthalten. Das wird für MKV und MP4
        # gleichermaßen per Bitstream-Rückprüfung erzwungen.
        strict_crop_rpu_verify = bool(getattr(state, "effective_crop", None))
        missing_dv = True
        missing_hdr10plus = require_hdr10plus

        if inspection.conclusive:
            profile = inspection.dolby_vision_profile
            if inspection.dolby_vision:
                dv_label = f"JA – Profil {profile}" if profile and profile != "Ja" else "JA"
            else:
                dv_label = "NEIN"
            hdr_label = "JA" if inspection.hdr10plus else "NEIN"
            self._vlog(f"[DV][VERIFY] MediaInfo: Dolby Vision={dv_label}; HDR10+={hdr_label}")

            missing_dv = not inspection.dolby_vision
            missing_hdr10plus = bool(require_hdr10plus and not inspection.hdr10plus)
            if not missing_dv:
                state.verified_dolby_vision = True
            if require_hdr10plus and not missing_hdr10plus:
                state.verified_hdr10plus = True

            if not missing_dv and not missing_hdr10plus:
                container = str(getattr(req, "container", "mp4") or "mp4").upper()
                if not strict_crop_rpu_verify:
                    self._log(
                        f"✅ [DV][VERIFY] Finales {container}: Dolby Vision {dv_label} | HDR10+ {hdr_label}",
                        "info",
                    )
                    return True
                self._log(
                    f"ℹ️  [DV][VERIFY] Physischer Crop aktiv – finale RPU wird im {container} "
                    "zusätzlich bytegenau gegen die verifizierte Crop-RPU geprüft.",
                    "info",
                )
                return verify_fallback(
                    state,
                    runner,
                    verify_dv=True,
                    verify_hdr10plus=False,
                )

            missing = []
            if missing_dv:
                missing.append("Dolby Vision")
            if missing_hdr10plus:
                missing.append("HDR10+")
            self._log(
                "⚠️  [DV][VERIFY] MediaInfo bestätigt "
                + " / ".join(missing)
                + " nicht. Starte Bitstream-Fallbackprüfung.",
                "warn",
            )
        else:
            detail = next((w for w in inspection.warnings if w), "keine Videospur erkannt")
            self._log(
                f"⚠️  [DV][VERIFY] MediaInfo-Ergebnis unklar ({detail}). "
                "Starte Bitstream-Fallbackprüfung.",
                "warn",
            )

        return verify_fallback(
            state,
            runner,
            verify_dv=bool(missing_dv or strict_crop_rpu_verify),
            verify_hdr10plus=missing_hdr10plus,
        )

    def verify_final_mux_metadata_fallback(
        self,
        state: DVPipelineState,
        runner: DVCommandRunner,
        *,
        verify_dv: bool,
        verify_hdr10plus: bool,
        sha256_file: Callable[[Path], str],
    ) -> bool:
        """Strenge Post-Mux-Bitstream-Prüfung nur für MediaInfo-offene Merkmale."""
        req, files = state.request, state.files
        if not verify_dv and not verify_hdr10plus:
            return True

        final_hevc = files.root / "final_mux_verify.hevc"
        final_rpu = files.root / "final_mux_verify.rpu"
        final_hdr_json = files.root / "final_mux_hdr10plus_verify.json"
        for path in (final_hevc, final_rpu, final_hdr_json):
            path.unlink(missing_ok=True)

        container = str(getattr(req, "container", "mp4") or "mp4")
        self._log(f"ℹ️  [DV][FALLBACK] Finalen {container.upper()}-Bitstream prüfen", "info")
        extract_cmd = [
            self._tools.ffmpeg, "-y", "-loglevel", "error",
            "-i", req.output_path, "-map", "0:v:0", "-c:v", "copy",
        ]
        if container.lower() == "mp4":
            extract_cmd += ["-bsf:v", "hevc_mp4toannexb"]
        extract_cmd += ["-an", "-sn", "-dn", "-f", "hevc", str(final_hevc)]
        rc = runner.run(
            extract_cmd,
            timeout=_TIMEOUT_HEVC_EXTRACT(),
            label="STEP 7/7 Post-Mux HEVC-Fallbackprüfung",
        )
        if rc != 0 or not self._assert_nonempty_file(final_hevc, "STEP 7 Post-Mux HEVC-Fallbackprüfung"):
            return False

        if verify_dv:
            run_rpu = runner.adapter(
                timeout=_TIMEOUT_RPU_EXTRACT(),
                label="STEP 7/7 Post-Mux RPU-Fallbackprüfung",
            )
            if not self._rpu_service.extract_rpu(
                run_rpu,
                input_hevc=final_hevc,
                output_rpu=final_rpu,
            ):
                self._log(f"❌ [DV][FALLBACK] Dolby-Vision-RPU ist im finalen {container.upper()} nicht nachweisbar.", "error")
                return False
            if not self._assert_nonempty_file(final_rpu, "STEP 7 Post-Mux RPU-Fallbackprüfung"):
                return False
            if state.rpu_to_use is None or sha256_file(state.rpu_to_use) != sha256_file(final_rpu):
                reason = f"Dolby-Vision-RPU im finalen {container.upper()} weicht von der injizierten RPU ab."
                self._temp_state.record_failure(
                    reason=reason,
                    stage="STEP 7/7 Post-Mux Metadaten-Fallbackprüfung",
                )
                self._log(
                    f"❌ [DV][FALLBACK] Dolby-Vision-RPU weicht nach {container.upper()}-Mux ab.",
                    "error",
                )
                return False
            state.verified_dolby_vision = True
            self._log("✅ [DV][FALLBACK] Dolby Vision im finalen Bitstream bestätigt.", "info")

        if verify_hdr10plus:
            run_hdr = runner.adapter(
                timeout=_TIMEOUT_HEVC_EXTRACT(),
                label="STEP 7/7 Post-Mux HDR10+-Fallbackprüfung",
            )
            if not self._hdr10plus_service.verify_metadata(
                run_hdr,
                source_stream=final_hevc,
                scratch_json=final_hdr_json,
                expected_json=files.hdr10plus_json,
            ):
                reason = (
                    f"HDR10+-Metadaten sind nach dem {container.upper()}-Mux "
                    "nicht identisch nachweisbar."
                )
                self._temp_state.record_failure(
                    reason=reason,
                    stage="STEP 7/7 Post-Mux Metadaten-Fallbackprüfung",
                )
                self._log("❌ [DV+HDR10+][FALLBACK] HDR10+-Nachprüfung fehlgeschlagen.", "error")
                return False
            state.verified_hdr10plus = True
            self._log("✅ [DV+HDR10+][FALLBACK] HDR10+ im finalen Bitstream bestätigt.", "info")

        self._log("✅ [DV][FALLBACK] Offene dynamische Metadaten bestätigt.", "info")
        return True
