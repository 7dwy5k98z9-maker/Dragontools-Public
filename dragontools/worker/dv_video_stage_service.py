# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .command_formatting import command_to_log_string as _cmd_str
from .dv_command_runner import DVCommandRunner
from .dv_crop_reconcile import reconcile_dv_crop, replace_crop_in_vf_args
from .dv_encode_command import build_dv_encode_command, primary_ffmpeg_video_index
from .dv_matroska_track_selection import select_matroska_video_track_number
from .encoder_args import encoder_10bit_filter_pixel_format
from .frame_count_evidence import FrameCountEvidence, temporal_mapping_for_filters
from .dv_pipeline_context import DVPipelineState
from .dv_partial_frame_repair import DVPartialFrameRepair
from .dv_edge_frame_repair import DVEdgeFrameRepair
from .dv_pipeline_timeouts import (
    timeout_dovi_editor as _TIMEOUT_DOVI_EDITOR,
    timeout_encode as _TIMEOUT_ENCODE,
    timeout_hevc_extract as _TIMEOUT_HEVC_EXTRACT,
    timeout_rpu_extract as _TIMEOUT_RPU_EXTRACT,
    timeout_mkvmerge as _TIMEOUT_MKVMERGE,
)
from ..core.media_hdr_detection import choose_dovi_convert_mode


def _dovi_tool_can_read_container_directly(input_path: str | Path) -> bool:
    """Return True for Matroska inputs supported by dovi_tool extract-rpu.

    dovi_tool can extract RPU directly from Matroska, but not from arbitrary
    containers such as MP4.  Keeping the fallback here avoids reintroducing a
    raw-HEVC picture source for MKV while preserving non-Matroska compatibility.
    """
    return Path(input_path).suffix.lower() in {".mkv", ".mk3d"}


class DVVideoStageService:
    """Qt-freie DV-Videovorbereitung bis einschließlich Video-Encode."""

    def __init__(
        self,
        *,
        tools,
        encoder_config,
        progress_runner,
        temp_state,
        hdr10plus_service,
        rpu_service,
        failure_recovery,
        log: Callable[[str, str], None],
        verbose_log: Callable[[str], None],
        assert_nonempty_file: Callable[[Path, str], bool],
        clear_burn_sub_tmp: Callable[[], None],
        crop_decision: Callable[[dict], str] | None = None,
    ) -> None:
        self._tools = tools
        self._encoder_config = encoder_config
        self._progress_runner = progress_runner
        self._temp_state = temp_state
        self._hdr10plus_service = hdr10plus_service
        self._rpu_service = rpu_service
        self._failure_recovery = failure_recovery
        self._log = log
        self._vlog = verbose_log
        self._assert_nonempty_file = assert_nonempty_file
        self._clear_burn_sub_tmp = clear_burn_sub_tmp
        self._crop_decision = crop_decision

    def _source_stream_selector(self, state: DVPipelineState) -> str:
        index = primary_ffmpeg_video_index(state.request.media_info)
        return f"0:{index}" if index is not None else "0:v:0"

    def _resolve_matroska_track_number(
        self, state: DVPipelineState, runner: DVCommandRunner
    ) -> int | None:
        """Resolve dovi_tool ``-t`` via Matroska ``properties.number``.

        dovi_tool's Matroska selector is not an FFmpeg stream index and not the
        zero-based mkvmerge ``id``.  Map the analyzed primary FFmpeg stream to
        the same video ordinal, then use the EBML TrackNumber.
        """
        mkvmerge = str(getattr(self._tools, "mkvmerge", "") or "").strip()
        if not mkvmerge:
            reason = (
                "Matroska-TrackNumber für dovi_tool kann nicht aufgelöst werden, "
                "weil mkvmerge nicht konfiguriert ist"
            )
            self._temp_state.record_failure(reason=reason, stage="STEP 3/7 RPU-Trackauflösung")
            self._log(f"❌ [DV] {reason}.", "error")
            return None

        proc = runner.run(
            [mkvmerge, "-J", state.request.input_path],
            return_process=True,
            timeout=_TIMEOUT_MKVMERGE(),
            label="STEP 3/7 Matroska-Trackauflösung",
        )
        if proc is None or int(getattr(proc, "returncode", 2)) not in (0, 1):
            return None
        try:
            payload = json.loads(str(getattr(proc, "stdout", "") or ""))
        except (TypeError, ValueError) as exc:
            reason = f"mkvmerge -J lieferte kein gültiges JSON für die DV-Trackauflösung: {exc}"
            self._temp_state.record_failure(reason=reason, stage="STEP 3/7 RPU-Trackauflösung")
            self._log(f"❌ [DV] {reason}", "error")
            return None

        try:
            track_number = select_matroska_video_track_number(payload, state.request.media_info)
        except ValueError as exc:
            self._temp_state.record_failure(reason=str(exc), stage="STEP 3/7 RPU-Trackauflösung")
            self._log(f"❌ [DV] {exc}", "error")
            return None
        self._vlog(f"[DV][STEP 3/7] Matroska TrackNumber {track_number} für die primäre FFmpeg-Videospur bestätigt.")
        return track_number

    def extract_source_hevc(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        """Prepare only metadata-side raw HEVC when the source container requires it.

        Matroska sources (P5/P7/P8) no longer create ``source.hevc`` for Dolby
        Vision: dovi_tool reads the MKV directly and the picture encode also reads
        the MKV directly.  A raw HEVC helper is still created when HDR10+ metadata
        must be extracted or when the source container is not Matroska (for
        example MP4), because dovi_tool ``extract-rpu`` cannot read arbitrary
        containers directly.  The helper is never used as the picture encode
        source.
        """
        req, files = state.request, state.files
        direct_rpu = _dovi_tool_can_read_container_directly(req.input_path)
        need_raw_rpu = not direct_rpu
        need_raw_hdr10plus = bool(req.preserve_dv_hdr10plus_combo)

        if not need_raw_rpu and not need_raw_hdr10plus:
            self._log(
                f"ℹ️  [DV][STEP 1/7] P{req.profile_major or '?'}: kein source.hevc nötig – "
                "RPU und Video werden direkt aus der MKV gelesen.",
                "info",
            )
            return True

        purposes = []
        if need_raw_rpu:
            purposes.append("RPU-Fallback für Nicht-Matroska")
        if need_raw_hdr10plus:
            purposes.append("HDR10+-Metadaten")
        self._log(
            "ℹ️  [DV][STEP 1/7] Temporärer HEVC-Hilfsstream nur für " + " + ".join(purposes),
            "info",
        )
        rc = runner.run(
            [
                self._tools.ffmpeg, "-y",
                "-i", req.input_path,
                "-map", self._source_stream_selector(state), "-c:v", "copy",
                "-bsf:v", "hevc_mp4toannexb",
                "-an", "-sn", "-dn", "-f", "hevc", str(files.src_hevc),
            ],
            timeout=_TIMEOUT_HEVC_EXTRACT(),
            label="STEP 1/7 DV-Metadaten-Hilfsstream",
        )
        if rc != 0 or not self._assert_nonempty_file(
            files.src_hevc, "STEP 1 DV-Metadaten-Hilfsstream"
        ):
            self._log(
                "❌ [DV] HEVC-Hilfsstream für dynamische Metadaten konnte nicht erstellt werden.",
                "error",
            )
            return False

        if not need_raw_hdr10plus:
            return True

        run_extract = runner.adapter(
            timeout=_TIMEOUT_HEVC_EXTRACT(),
            label="DV+HDR10+ Metadata-Extract",
        )
        if not self._hdr10plus_service.extract_metadata(
            run_extract,
            source_stream=files.src_hevc,
            output_json=files.hdr10plus_json,
        ):
            self._log(
                "❌ [DV+HDR10+] HDR10+-Metadaten konnten nicht aus der Quelle extrahiert werden.",
                "error",
            )
            return False
        return True

    def convert_profile_to_81(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        """Compatibility stage: P8.1 normalization now happens during RPU extraction.

        ``dovi_tool -m <mode> extract-rpu`` applies the same RPU conversion
        without rewriting the full HEVC stream.  Keeping this stage as a no-op
        avoids breaking older stage instrumentation while removing p8.hevc from
        the productive encoder path.
        """
        req = state.request
        mode = choose_dovi_convert_mode(req.media_info)
        state.profile_hevc = None
        self._log(
            f"ℹ️  [DV][STEP 2/7] Profilnormalisierung wird direkt bei der RPU-Extraktion angewendet "
            f"(dovi_tool -m {mode}); kein p8.hevc wird erzeugt.",
            "info",
        )
        return True

    def extract_rpu(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        req, files = state.request, state.files
        mode = choose_dovi_convert_mode(req.media_info)
        direct_mkv = _dovi_tool_can_read_container_directly(req.input_path)
        rpu_source = Path(req.input_path) if direct_mkv else files.src_hevc
        source_label = "MKV" if direct_mkv else "HEVC-Metadaten-Hilfsstream"
        self._log(
            f"ℹ️  [DV][STEP 3/7] P{req.profile_major or '?'}: RPU aus {source_label} extrahieren "
            f"und auf P8.1 normalisieren (dovi_tool -m {mode})",
            "info",
        )
        if not direct_mkv and not self._assert_nonempty_file(
            files.src_hevc, "STEP 3 RPU-Quellstream"
        ):
            return False
        run_extract = runner.adapter(
            timeout=_TIMEOUT_RPU_EXTRACT(),
            label="STEP 3/7 RPU-Extraktion",
        )
        kwargs = {
            "output_rpu": files.rpu_orig,
            "mode": mode,
        }
        if direct_mkv:
            kwargs["input_path"] = req.input_path
            # dovi_tool's default is unambiguous for a single video track.
            # Only multi-video Matroska needs an explicit EBML TrackNumber; in
            # that case never guess from FFmpeg/mkvmerge IDs.
            video_streams = list(getattr(req.media_info, "video_streams", []) or [])
            if len(video_streams) > 1:
                track_number = self._resolve_matroska_track_number(state, runner)
                if track_number is None:
                    return False
                kwargs["track_number"] = track_number
        else:
            kwargs["input_hevc"] = files.src_hevc
        if not self._rpu_service.extract_rpu(run_extract, **kwargs):
            self._log(
                "❌ [DV][STEP 3/7] ERROR - RPU-Extraktion/Normalisierung fehlgeschlagen.",
                "error",
            )
            return False
        return self._assert_nonempty_file(files.rpu_orig, "STEP 3 RPU-Extraktion")

    def reconcile_crop_from_rpu(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        """Synchronisiert FFmpeg-AutoCrop und RPU-Level-5 vor dem Video-Encode."""
        req, files = state.request, getattr(state, "files", None)
        if files is None or not hasattr(files, "rpu_orig") or not hasattr(files, "level5_source_json"):
            return True
        video = getattr(req.media_info, "primary_video", None)
        src_w = int(getattr(video, "width", 0) or 0)
        src_h = int(getattr(video, "height", 0) or 0)
        if src_w <= 0 or src_h <= 0:
            self._log("⚠️ [DV][CROP] Quellauflösung unbekannt – RPU/AutoCrop-Abgleich übersprungen.", "warn")
            return True
        outcome = reconcile_dv_crop(
            runner=runner,
            dovi_tool=self._tools.dovi_tool,
            rpu_path=files.rpu_orig,
            export_path=files.level5_source_json,
            source_width=src_w,
            source_height=src_h,
            autocrop_text=state.effective_crop,
            input_path=req.input_path,
            crop_decision=self._crop_decision,
            timeout=_TIMEOUT_DOVI_EDITOR(),
            log=self._log,
        )
        if not outcome.success:
            self._temp_state.record_failure(reason=outcome.failure_reason, stage="DV-Crop-Abgleich")
            if outcome.disable_dv:
                self._temp_state.failure_reason = "DV_DISABLED_BY_USER_CROP"
            else:
                self._log(f"❌ [DV][CROP] {outcome.failure_reason}", "error")
            return False
        selected_text = outcome.crop.as_filter() if outcome.crop else None
        previous = state.effective_crop
        state.effective_crop = selected_text
        state.effective_vf_args = replace_crop_in_vf_args(
            state.effective_vf_args or req.vf_args,
            previous,
            selected_text,
        )
        if selected_text != previous:
            source = "RPU" if outcome.source == "rpu" else "AutoCrop"
            self._log(
                f"✅ [DV][CROP] Effektiver Crop auf {selected_text or 'kein Crop'} "
                f"synchronisiert (Quelle: {source}).",
                "info",
            )
        return True

    def encode_video(self, state: DVPipelineState, _runner: DVCommandRunner) -> bool:
        req, files = state.request, state.files
        self._log("ℹ️  [DV][STEP 4/7] Video-Encoding", "info")

        plan = build_dv_encode_command(
            ffmpeg_path=self._tools.ffmpeg,
            encoder_config=self._encoder_config,
            input_path=req.input_path,
            p8_hevc=None,
            output_hevc=files.enc_hevc,
            vf_args=state.effective_vf_args or req.vf_args,
            profile_major=req.profile_major,
            source_stream_index=primary_ffmpeg_video_index(req.media_info),
        )
        if plan.uses_libplacebo:
            pixel_format = encoder_10bit_filter_pixel_format(self._encoder_config.options)
            self._vlog(
                "[DV][STEP 4/7] P5: libplacebo-HDR10-Base-Layer-Konvertierung "
                f"aus Originalcontainer startet (ICtCp → BT.2020nc/PQ/{pixel_format})."
            )
        else:
            self._vlog(
                f"[DV][STEP 4/7] P{req.profile_major or '?'}: Video-Encode direkt aus "
                "dem Originalcontainer; die normalisierte RPU läuft getrennt."
            )

        self._vlog(f"[DV CMD] {_cmd_str(plan.command)}")
        dur_ms = self._progress_runner.probe_ms(req.input_path)
        rc = self._progress_runner.run_p(
            plan.command,
            req.input_path,
            dur_ms,
            timeout_s=_TIMEOUT_ENCODE(),
            label="[DV][STEP 4/7] Video-Encoding",
        )
        if rc != 0 or not files.enc_hevc.exists() or files.enc_hevc.stat().st_size == 0:
            self._log(
                f"❌ [DV][STEP 4/7] ERROR - Video-Encoding fehlgeschlagen (rc={rc}).",
                "error",
            )
            if self._temp_state.stderr:
                for line in self._temp_state.stderr.splitlines()[-5:]:
                    if line.strip():
                        self._log(f"  ffmpeg: {line}", "error")
            self.cleanup_burn_sub(req)
            return False
        if not self._assert_nonempty_file(files.enc_hevc, "STEP 4 Video-Encoding"):
            self.cleanup_burn_sub(req)
            return False
        output_frames = self._progress_runner.take_output_frame_count(
            req.input_path,
            process_rc=rc,
        )
        if output_frames:
            state.encoded_frame_evidence = FrameCountEvidence.reliable(
                output_frames,
                source="ffmpeg_encode_progress",
                path=files.enc_hevc,
                stage="STEP 4/7 Video-Encoding",
                temporal_mapping=temporal_mapping_for_filters(state.effective_vf_args or req.vf_args),
            )
            self._vlog(
                f"[DV][STEP 4/7] Verlässliche Encoder-Ausgabebildzahl: {output_frames} Frames "
                f"(Quelle: ffmpeg -progress)."
            )
        else:
            state.encoded_frame_evidence = FrameCountEvidence.unknown(
                source="ffmpeg_encode_progress_missing",
                path=files.enc_hevc,
                stage="STEP 4/7 Video-Encoding",
            )
            self._vlog(
                "[DV][STEP 4/7] Encoder lieferte keine verlässliche Ausgabebildzahl; "
                "es wird kein geschätzter Wert als DV-Paritätsnachweis verwendet."
            )
        return True

    def ensure_frame_parity_or_recover(
        self,
        state: DVPipelineState,
        runner: DVCommandRunner,
        *,
        probe_rpu_frame_count: Callable[[DVCommandRunner, Path], int | None],
    ) -> bool:
        """Validate encoder progress against the extracted RPU before releasing the encode slot."""
        evidence = getattr(state, "encoded_frame_evidence", None)
        files = state.files
        if evidence is None or not evidence.is_reliable_for(files.enc_hevc):
            self._vlog(
                "[DV][RECOVERY] Kein verlässlicher Encoder-Framecount direkt nach STEP 4; "
                "die normale STEP-6-Paritätsprüfung bleibt als Guard aktiv."
            )
            return True
        if evidence.temporal_mapping == "changed":
            # The existing STEP-6 validator owns this policy error and produces
            # the more specific user-facing reason.
            return True

        rpu_count = probe_rpu_frame_count(runner, files.rpu_orig)
        if not rpu_count:
            self._vlog(
                "[DV][RECOVERY] RPU-Framecount direkt nach STEP 4 nicht ermittelbar; "
                "kein automatischer Retry ohne exakten Sollwert."
            )
            return True

        encode_count = int(evidence.count)
        self._log(f'[DV][POST-ENCODE-FRAME-CHECK] HEVC={encode_count}; RPU={rpu_count}', 'info')
        if int(rpu_count) == encode_count:
            self._vlog(
                f"[DV][STEP 4/7] Frühe RPU/Encode-Parität OK: {encode_count} Frames."
            )
            return True

        if encode_count > int(rpu_count) and self._attempt_edge_frame_repair(
            state,
            runner,
            expected_rpu_frames=int(rpu_count),
            actual_encode_frames=encode_count,
        ):
            state.encoded_frame_evidence = FrameCountEvidence.reliable(
                int(rpu_count),
                source="ffmpeg_edge_repair_validated",
                path=files.enc_hevc,
                stage="STEP 4/7 DV Edge-Recovery",
                temporal_mapping=evidence.temporal_mapping,
            )
            return True

        if self._attempt_partial_frame_repair(
            state,
            runner,
            expected_rpu_frames=int(rpu_count),
            actual_encode_frames=encode_count,
        ):
            state.encoded_frame_evidence = FrameCountEvidence.reliable(
                int(rpu_count),
                source="ffmpeg_partial_repair_validated",
                path=files.enc_hevc,
                stage="STEP 4/7 DV Partial-Recovery",
                temporal_mapping=evidence.temporal_mapping,
            )
            return True

        reason = (
            "RPU/Encode-Frame-Mismatch nach Video-Encoding: "
            f"RPU={int(rpu_count)}, HEVC={encode_count}. "
            "Eine konservative Rand- oder Teilreparatur des betroffenen GOP-Bereichs war nicht eindeutig und sicher möglich. "
            "Da der normale DV-Pfad bereits direkt aus der Original-MKV encodiert, wird kein identischer Voll-Reencode automatisch wiederholt."
        )
        self._temp_state.record_failure(reason=reason, stage="STEP 4/7 Frame-Recovery")
        self._log(f"❌ [DV][RECOVERY] {reason}", "error")
        return False

    def _attempt_edge_frame_repair(
        self,
        state: DVPipelineState,
        runner: DVCommandRunner,
        *,
        expected_rpu_frames: int,
        actual_encode_frames: int,
    ) -> bool:
        return DVEdgeFrameRepair(
            tools=self._tools,
            encoder_config=self._encoder_config,
            progress_runner=self._progress_runner,
            log=self._log,
            verbose_log=self._vlog,
        ).attempt(
            state=state,
            runner=runner,
            expected_rpu_frames=expected_rpu_frames,
            actual_encode_frames=actual_encode_frames,
        )

    def _attempt_partial_frame_repair(
        self,
        state: DVPipelineState,
        runner: DVCommandRunner,
        *,
        expected_rpu_frames: int,
        actual_encode_frames: int,
    ) -> bool:
        """Try the conservative GOP-bounded repair before failing the DV job."""
        return DVPartialFrameRepair(
            tools=self._tools,
            encoder_config=self._encoder_config,
            progress_runner=self._progress_runner,
            log=self._log,
            verbose_log=self._vlog,
        ).attempt(
            state=state,
            runner=runner,
            expected_rpu_frames=expected_rpu_frames,
            actual_encode_frames=actual_encode_frames,
        )

    def cleanup_burn_sub(self, request) -> None:
        self._failure_recovery.cleanup_tmp_sub(
            base_dir=Path(request.output_path).parent,
            tmp_sub=self._temp_state.burn_sub_tmp,
            clear_tmp_sub=self._clear_burn_sub_tmp,
        )
