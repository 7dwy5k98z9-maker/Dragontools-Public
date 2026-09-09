# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .command_formatting import command_to_log_string as _cmd_str
from .dv_command_runner import DVCommandRunner
from .dv_crop_reconcile import reconcile_dv_crop, replace_crop_in_vf_args
from .dv_encode_command import build_dv_encode_command
from .dv_pipeline_context import DVPipelineState
from .dv_pipeline_timeouts import (
    timeout_dovi_convert as _TIMEOUT_DOVI_CONVERT,
    timeout_dovi_editor as _TIMEOUT_DOVI_EDITOR,
    timeout_encode as _TIMEOUT_ENCODE,
    timeout_hevc_extract as _TIMEOUT_HEVC_EXTRACT,
    timeout_rpu_extract as _TIMEOUT_RPU_EXTRACT,
)
from ..core.media_hdr_detection import choose_dovi_convert_mode


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

    def extract_source_hevc(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        req, files = state.request, state.files
        self._log("ℹ️  [DV][STEP 1/7] HEVC", "info")
        rc = runner.run(
            [
                self._tools.ffmpeg, "-y",
                "-i", req.input_path,
                "-map", "0:v:0", "-c:v", "copy",
                "-bsf:v", "hevc_mp4toannexb",
                "-an", "-sn", "-dn", "-f", "hevc", str(files.src_hevc),
            ],
            timeout=_TIMEOUT_HEVC_EXTRACT(),
            label="STEP 1/7 HEVC-Extraktion",
        )
        if rc != 0:
            self._log("❌ [DV][STEP 1/7] ERROR - HEVC-Extraktion fehlgeschlagen.", "error")
            return False
        if not self._assert_nonempty_file(files.src_hevc, "STEP 1 HEVC-Extraktion"):
            return False

        if not req.preserve_dv_hdr10plus_combo:
            return True

        self._vlog("[DV+HDR10+][DETAIL] HDR10+-Metadaten aus Quelle extrahieren")
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
        req, files = state.request, state.files
        dovi_mode = choose_dovi_convert_mode(req.media_info)
        self._log(
            f"ℹ️  [DV][STEP 2/7] DV-Profilkonvertierung zu 8.1 "
            f"(Profil: {getattr(req.media_info, 'dv_profile', None) or 'unbekannt'}, "
            f"dovi_tool -m {dovi_mode})",
            "info",
        )
        rc = runner.run(
            [
                self._tools.dovi_tool, "-m", dovi_mode, "convert",
                "--discard", str(files.src_hevc), "-o", str(files.p8_hevc),
            ],
            timeout=_TIMEOUT_DOVI_CONVERT(),
            label="STEP 2/7 DV-Profilkonvertierung",
        )
        if rc != 0:
            self._log("❌ [DV][STEP 2/7] ERROR - DV-Profilkonvertierung fehlgeschlagen.", "error")
            return False
        if not self._assert_nonempty_file(files.p8_hevc, "STEP 2 DV-Profilkonvertierung"):
            return False
        state.profile_hevc = files.p8_hevc
        return True

    def extract_rpu(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        files = state.files
        input_hevc = state.profile_hevc or files.p8_hevc
        self._log("ℹ️  [DV][STEP 3/7] RPU-Extraktion", "info")
        run_extract = runner.adapter(
            timeout=_TIMEOUT_RPU_EXTRACT(),
            label="STEP 3/7 RPU-Extraktion",
        )
        if not self._rpu_service.extract_rpu(
            run_extract,
            input_hevc=input_hevc,
            output_rpu=files.rpu_orig,
        ):
            self._log("❌ [DV][STEP 3/7] ERROR - RPU-Extraktion fehlgeschlagen.", "error")
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

        profile_hevc = state.profile_hevc or files.p8_hevc
        plan = build_dv_encode_command(
            ffmpeg_path=self._tools.ffmpeg,
            encoder_config=self._encoder_config,
            input_path=req.input_path,
            p8_hevc=profile_hevc,
            output_hevc=files.enc_hevc,
            vf_args=state.effective_vf_args or req.vf_args,
            profile_major=req.profile_major,
        )
        if plan.uses_libplacebo:
            self._vlog(
                "[DV][STEP 4/7] P5: libplacebo-HDR10-Base-Layer-Konvertierung "
                "aus Originalcontainer startet (ICtCp → BT.2020nc/PQ/p010le)."
            )
        else:
            self._vlog(
                f"[DV][STEP 4/7] P{req.profile_major or '?'}: Encode aus "
                f"DV-Arbeitsstream {profile_hevc.name}."
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
        self.cleanup_burn_sub(req)
        return True

    def cleanup_burn_sub(self, request) -> None:
        self._failure_recovery.cleanup_tmp_sub(
            base_dir=Path(request.output_path).parent,
            tmp_sub=self._temp_state.burn_sub_tmp,
            clear_tmp_sub=self._clear_burn_sub_tmp,
        )
