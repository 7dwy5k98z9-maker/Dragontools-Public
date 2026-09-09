# -*- coding: utf-8 -*-
from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Callable

from .dv_command_runner import DVCommandRunner
from .dv_pipeline_context import DVPipelineState
from .dv_pipeline_timeouts import (
    timeout_dovi_editor as _TIMEOUT_DOVI_EDITOR,
    timeout_hevc_extract as _TIMEOUT_HEVC_EXTRACT,
    timeout_rpu_extract as _TIMEOUT_RPU_EXTRACT,
    timeout_rpu_inject as _TIMEOUT_RPU_INJECT,
)


class DVDynamicMetadataService:
    """Qt-freie DV/HDR10+-Metadatenstufen nach dem Video-Encode."""

    def __init__(
        self,
        *,
        tools,
        temp_state,
        audio_mux_service,
        rpu_service,
        hdr10plus_service,
        level5_editor,
        failure_recovery,
        log: Callable[[str, str], None],
        verbose_log: Callable[[str], None],
        assert_nonempty_file: Callable[[Path, str], bool],
    ) -> None:
        self._tools = tools
        self._temp_state = temp_state
        self._audio_mux_service = audio_mux_service
        self._rpu_service = rpu_service
        self._hdr10plus_service = hdr10plus_service
        self._level5_editor = level5_editor
        self._failure_recovery = failure_recovery
        self._log = log
        self._vlog = verbose_log
        self._assert_nonempty_file = assert_nonempty_file

    def resolve_rpu_crop(
        self,
        state: DVPipelineState,
        runner: DVCommandRunner,
        *,
        save_crop_failure: Callable[..., Path],
    ) -> bool:
        req, files = state.request, state.files
        self._log("ℹ️  [DV][STEP 5/7] RPU-Crop / Level-5", "info")
        run_editor = runner.adapter(
            timeout=_TIMEOUT_DOVI_EDITOR(),
            label="STEP 5/7 dovi_tool editor",
        )
        state.rpu_to_use = self._level5_editor.resolve_rpu_for_crop(
            run_editor,
            crop=state.effective_crop,
            media_info=req.media_info,
            rpu_orig=files.rpu_orig,
            rpu_final=files.rpu_final,
            edit_json=files.edit_json,
            save_failure_artifacts=lambda level5_proc=None: save_crop_failure(
                state,
                runner,
                level5_proc=level5_proc,
            ),
        )
        if state.rpu_to_use is None:
            self._log(
                "❌ [DV][STEP 5/7] ERROR - RPU-Crop-Auflösung fehlgeschlagen - Abbruch.",
                "error",
            )
            return False
        return self._assert_nonempty_file(state.rpu_to_use, "STEP 6 RPU-Crop")

    def save_crop_failure(
        self,
        state: DVPipelineState,
        runner: DVCommandRunner,
        *,
        mux_plain_mp4_without_dv: Callable[[DVPipelineState, DVCommandRunner], bool],
        level5_proc=None,
    ) -> Path:
        req, files = state.request, state.files
        return self._failure_recovery.save_dv_crop_failure(
            input_path=req.input_path,
            output_path=req.output_path,
            crop=state.effective_crop,
            plain_mp4=files.plain_mp4,
            src_hevc=files.src_hevc,
            enc_hevc=files.enc_hevc,
            rpu_orig=files.rpu_orig,
            rpu_final=files.rpu_final,
            edit_json=files.edit_json,
            audio_tracks=state.audio_tracks,
            mux_plain_mp4_without_dv=lambda: mux_plain_mp4_without_dv(state, runner),
            level5_proc=level5_proc,
        )

    def mux_plain_mp4_without_dv(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        req, files = state.request, state.files
        ok, tracks = self._audio_mux_service.mux_plain_mp4_without_dv(
            input_path=req.input_path,
            enc_mkv=None,
            audio_mux_src=files.audio_mux_src,
            enc_hevc=files.enc_hevc,
            plain_mp4=files.plain_mp4,
            audio_args=req.audio_args,
            audio_meta=state.audio_meta,
            audio_tracks=state.audio_tracks,
            tmp_dir=files.root,
            run_fn=runner.run,
        )
        state.audio_tracks = tracks
        return ok

    def inject_dynamic_metadata(
        self,
        state: DVPipelineState,
        runner: DVCommandRunner,
        *,
        validate_rpu_frame_parity: Callable[..., bool],
        verify_injected_rpu: Callable[..., bool],
    ) -> bool:
        req, files = state.request, state.files
        rpu_input_hevc = files.enc_hevc

        if req.preserve_dv_hdr10plus_combo:
            self._vlog("[DV+HDR10+][DETAIL] HDR10+-Metadaten injizieren")
            run_hdr_inject = runner.adapter(
                timeout=_TIMEOUT_RPU_INJECT(),
                label="DV+HDR10+ Metadata-Injection",
            )
            if not self._hdr10plus_service.inject_metadata(
                run_hdr_inject,
                input_hevc=files.enc_hevc,
                metadata_json=files.hdr10plus_json,
                output_hevc=files.hdr10plus_hevc,
            ):
                self._log(
                    "❌ [DV+HDR10+] HDR10+-Metadaten konnten nicht in den Encode injiziert werden.",
                    "error",
                )
                return False
            if not self._assert_nonempty_file(files.hdr10plus_hevc, "DV+HDR10+ HDR10+-Injection"):
                return False
            rpu_input_hevc = files.hdr10plus_hevc

        state.rpu_input_hevc = rpu_input_hevc
        if not validate_rpu_frame_parity(
            runner,
            rpu_path=state.rpu_to_use,
            hevc_path=rpu_input_hevc,
        ):
            return False

        self._log("ℹ️  [DV][STEP 6/7] Dynamische Metadaten (DV/HDR10+)", "info")
        run_rpu_inject = runner.adapter(
            timeout=_TIMEOUT_RPU_INJECT(),
            label="STEP 6/7 RPU-Injektion",
        )
        if not self._rpu_service.inject_rpu(
            run_rpu_inject,
            input_hevc=rpu_input_hevc,
            input_rpu=state.rpu_to_use,
            output_hevc=files.injected,
        ):
            self._log("❌ [DV][STEP 6/7] ERROR - RPU-Injektion fehlgeschlagen.", "error")
            return False
        if not self._assert_nonempty_file(files.injected, "STEP 6 RPU-Injektion"):
            return False
        if not verify_injected_rpu(
            runner,
            injected_hevc=files.injected,
            expected_rpu=state.rpu_to_use,
            scratch_rpu=files.rpu_verify,
        ):
            return False

        if not req.preserve_dv_hdr10plus_combo:
            return True

        self._vlog("[DV+HDR10+][DETAIL] HDR10+-Nachprüfung vor MP4Box")
        run_hdr_verify = runner.adapter(
            timeout=_TIMEOUT_HEVC_EXTRACT(),
            label="DV+HDR10+ Metadata-Prüfung",
        )
        if not self._hdr10plus_service.verify_metadata(
            run_hdr_verify,
            source_stream=files.injected,
            scratch_json=files.hdr10plus_verify_json,
            expected_json=files.hdr10plus_json,
        ):
            self._log(
                "❌ [DV+HDR10+] HDR10+-Metadaten sind nach der DV-RPU-Injektion nicht mehr nachweisbar.",
                "error",
            )
            return False
        self._vlog(
            "[DV+HDR10+] Zwischenprüfung: DV und HDR10+ im injizierten HEVC-Bitstream bestätigt."
        )
        return True

    def validate_rpu_frame_parity(
        self,
        runner: DVCommandRunner,
        *,
        rpu_path: Path,
        hevc_path: Path,
        probe_rpu_frame_count: Callable[[DVCommandRunner, Path], int | None] | None = None,
        probe_hevc_frame_count: Callable[[DVCommandRunner, Path], int | None] | None = None,
    ) -> bool:
        """Bricht nur bei eindeutig nachweisbarer Frame-Differenz ab."""
        rpu_probe = probe_rpu_frame_count or self.probe_rpu_frame_count
        hevc_probe = probe_hevc_frame_count or self.probe_hevc_frame_count
        rpu_count = rpu_probe(runner, rpu_path)
        hevc_count = hevc_probe(runner, hevc_path)
        if rpu_count is None or hevc_count is None:
            self._vlog(
                "[DV][STEP 6/7] Frame-Paritaet konnte nicht vollstaendig bestimmt werden; "
                "Injection bleibt fail-closed ueber Tool-RC und RPU-Rueckpruefung."
            )
            return True
        if rpu_count == hevc_count:
            self._vlog(f"[DV][STEP 6/7] Frame-Paritaet OK: {rpu_count} Frames.")
            return True
        reason = (
            "RPU/Encode-Frame-Mismatch vor Injection: "
            f"RPU={rpu_count}, HEVC={hevc_count}."
        )
        self._temp_state.record_failure(reason=reason, stage="STEP 6/7 RPU-Injektion")
        self._log(f"❌ [DV] {reason}", "error")
        return False

    def probe_rpu_frame_count(self, runner: DVCommandRunner, path: Path) -> int | None:
        proc = runner.run(
            [self._tools.dovi_tool, "info", "-s", str(path)],
            allow_error=True,
            return_process=True,
            timeout=_TIMEOUT_RPU_EXTRACT(),
            label="STEP 6/7 RPU-Frameprüfung",
        )
        if proc is None or getattr(proc, "returncode", 1) != 0:
            return None
        text = f"{getattr(proc, 'stdout', '')}\n{getattr(proc, 'stderr', '')}"
        patterns = (
            r"(?im)\bframes?\b\s*[:=]\s*(\d+)",
            r"(?im)\bframe\s+count\b\s*[:=]\s*(\d+)",
            r"(?im)\blength\b\s*[:=]\s*(\d+)\s*frames?",
        )
        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                return int(match.group(1))
        return None

    def probe_hevc_frame_count(self, runner: DVCommandRunner, path: Path) -> int | None:
        proc = runner.run(
            [
                self._tools.ffprobe, "-v", "error", "-count_frames",
                "-select_streams", "v:0", "-show_entries",
                "stream=nb_read_frames,nb_frames", "-of", "default=nw=1", str(path),
            ],
            allow_error=True,
            return_process=True,
            timeout=_TIMEOUT_HEVC_EXTRACT(),
            label="STEP 6/7 HEVC-Frameprüfung",
        )
        if proc is None or getattr(proc, "returncode", 1) != 0:
            return None
        text = str(getattr(proc, "stdout", "") or "")
        for match in re.finditer(r"(?:nb_read_frames|nb_frames)=(\d+)", text):
            value = int(match.group(1))
            if value > 0:
                return value
        return None

    def verify_injected_rpu(
        self,
        runner: DVCommandRunner,
        *,
        injected_hevc: Path,
        expected_rpu: Path,
        scratch_rpu: Path,
    ) -> bool:
        scratch_rpu.unlink(missing_ok=True)
        run_extract = runner.adapter(
            timeout=_TIMEOUT_RPU_EXTRACT(),
            label="STEP 6/7 RPU-Nachprüfung",
        )
        if not self._rpu_service.extract_rpu(
            run_extract,
            input_hevc=injected_hevc,
            output_rpu=scratch_rpu,
        ):
            self._log("❌ [DV] RPU konnte nach der Injection nicht erneut extrahiert werden.", "error")
            return False
        if not self._assert_nonempty_file(scratch_rpu, "STEP 6 RPU-Nachprüfung"):
            return False
        if self.sha256(expected_rpu) != self.sha256(scratch_rpu):
            reason = "RPU-Inhalt nach Injection weicht von der geplanten RPU ab."
            self._temp_state.record_failure(reason=reason, stage="STEP 6/7 RPU-Injektion")
            self._log(f"❌ [DV] {reason}", "error")
            return False
        self._vlog("[DV][STEP 6/7] RPU-Nachprüfung OK (SHA-256 identisch).")
        return True

    @staticmethod
    def sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()
