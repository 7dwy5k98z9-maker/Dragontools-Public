# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .dv_command_runner import DVCommandRunner
from .dv_dynamic_metadata_service import DVDynamicMetadataService
from .dv_final_mux_service import DVFinalMuxService
from .dv_pipeline_context import DVPipelineResult, DVPipelineState
from .dv_video_stage_service import DVVideoStageService
from ..core.media_analyzer import inspect_dynamic_hdr_with_mediainfo
from ..rules.subtitle_rules import any_sidecar_export_enabled


def _video_service(owner: "DVPipelineStages") -> DVVideoStageService:
    return DVVideoStageService(
        tools=getattr(owner, "_tools", None),
        encoder_config=getattr(owner, "_encoder_config", None),
        progress_runner=getattr(owner, "_progress_runner", None),
        temp_state=getattr(owner, "_temp_state", None),
        hdr10plus_service=getattr(owner, "_hdr10plus_service", None),
        rpu_service=getattr(owner, "_rpu_service", None),
        failure_recovery=getattr(owner, "_failure_recovery", None),
        log=getattr(owner, "_log", lambda *_args, **_kwargs: None),
        verbose_log=getattr(owner, "_vlog", lambda *_args, **_kwargs: None),
        assert_nonempty_file=getattr(owner, "_assert_nonempty_file", lambda *_args: False),
        clear_burn_sub_tmp=getattr(owner, "_clear_burn_sub_tmp", lambda: None),
        crop_decision=getattr(owner, "_crop_decision", None),
    )


def _metadata_service(owner: "DVPipelineStages") -> DVDynamicMetadataService:
    return DVDynamicMetadataService(
        tools=getattr(owner, "_tools", None),
        temp_state=getattr(owner, "_temp_state", None),
        audio_mux_service=getattr(owner, "_audio_mux_service", None),
        rpu_service=getattr(owner, "_rpu_service", None),
        hdr10plus_service=getattr(owner, "_hdr10plus_service", None),
        level5_editor=getattr(owner, "_level5_editor", None),
        failure_recovery=getattr(owner, "_failure_recovery", None),
        log=getattr(owner, "_log", lambda *_args, **_kwargs: None),
        verbose_log=getattr(owner, "_vlog", lambda *_args, **_kwargs: None),
        assert_nonempty_file=getattr(owner, "_assert_nonempty_file", lambda *_args: False),
    )


def _mux_service(owner: "DVPipelineStages") -> DVFinalMuxService:
    return DVFinalMuxService(
        tools=getattr(owner, "_tools", None),
        temp_state=getattr(owner, "_temp_state", None),
        audio_mux_service=getattr(owner, "_audio_mux_service", None),
        mp4box_muxer=getattr(owner, "_mp4box_muxer", None),
        mkv_muxer=getattr(owner, "_mkv_muxer", None),
        rpu_service=getattr(owner, "_rpu_service", None),
        hdr10plus_service=getattr(owner, "_hdr10plus_service", None),
        subtitle_mux_service=getattr(owner, "_subtitle_mux_service", None),
        subtitle_rules=getattr(owner, "_subtitle_rules", {}),
        log=getattr(owner, "_log", lambda *_args, **_kwargs: None),
        verbose_log=getattr(owner, "_vlog", lambda *_args, **_kwargs: None),
        assert_nonempty_file=getattr(owner, "_assert_nonempty_file", lambda *_args: False),
    )


class DVPipelineStages:
    """DV-Stufenkoordinator mit stabilen Kompatibilitäts-Delegationspunkten.

    Die eigentliche Fachlogik lebt in Qt-freien Services. Die privaten
    Stufenmethoden bleiben bewusst als dünne Übergangsschnittstellen bestehen,
    weil bestehende Regressionstests und einzelne interne Aufrufer sie patchen.
    """

    def __init__(
        self,
        *,
        tools,
        encoder_config,
        progress_runner,
        temp_state,
        audio_mux_service,
        mp4box_muxer,
        mkv_muxer=None,
        rpu_service=None,
        hdr10plus_service,
        level5_editor,
        subtitle_service,
        subtitle_mux_service=None,
        subtitle_rules: dict | None = None,
        failure_recovery=None,
        log: Callable[[str, str], None],
        verbose_log: Callable[[str], None],
        assert_nonempty_file: Callable[[Path, str], bool],
        clear_burn_sub_tmp: Callable[[], None],
        crop_decision: Callable[[dict], str] | None = None,
    ) -> None:
        # Diese Alias-Felder bleiben für bestehende interne Diagnose-/Testschnittstellen
        # erhalten. Fachlogik darf sie nur über die Service-Verdrahtung verwenden.
        self._tools = tools
        self._encoder_config = encoder_config
        self._progress_runner = progress_runner
        self._temp_state = temp_state
        self._audio_mux_service = audio_mux_service
        self._mp4box_muxer = mp4box_muxer
        self._mkv_muxer = mkv_muxer
        self._rpu_service = rpu_service
        self._hdr10plus_service = hdr10plus_service
        self._level5_editor = level5_editor
        self._subtitle_service = subtitle_service
        self._subtitle_mux_service = subtitle_mux_service
        self._subtitle_rules = dict(subtitle_rules or {})
        self._failure_recovery = failure_recovery
        self._log = log
        self._vlog = verbose_log
        self._assert_nonempty_file = assert_nonempty_file
        self._clear_burn_sub_tmp = clear_burn_sub_tmp
        self._crop_decision = crop_decision

    def _initialize_run_state(self, state: DVPipelineState) -> None:
        request = state.request
        state.audio_meta = self._audio_mux_service.build_audio_meta(
            request.media_info,
            request.override,
            getattr(request, "container", "mp4"),
        )
        state.effective_crop = getattr(request, "crop", None)
        state.effective_vf_args = list(getattr(request, "vf_args", []) or [])
        self._vlog(
            f"[TRACE][DV] audio meta built: {len(state.audio_meta)} track(s), "
            f"crop={state.effective_crop or '-'}"
        )
        if request.preserve_dv_hdr10plus_combo:
            self._log(
                "ℹ️  [DV+HDR10+] Kombipfad aktiv: Dolby Vision und HDR10+ werden gemeinsam erhalten.",
                "info",
            )

    def run(self, state: DVPipelineState, runner: DVCommandRunner) -> DVPipelineResult:
        """Orchestriert die Stufen; jede Stufe darf den Ablauf sauber abbrechen."""
        request = state.request
        self._initialize_run_state(state)

        stages = (
            ("STEP 1/7 HEVC-Extraktion", self._extract_source_hevc),
            ("STEP 2/7 DV-Profilkonvertierung", self._convert_profile_to_81),
            ("STEP 3/7 RPU-Extraktion", self._extract_rpu),
            ("DV-Crop-Abgleich", self._reconcile_crop_from_rpu),
            ("STEP 4/7 Video-Encoding", self._encode_video),
            ("STEP 5/7 RPU-Crop / Level-5", self._resolve_rpu_crop),
            ("STEP 6/7 Dynamische Metadaten", self._inject_dynamic_metadata),
            ("Audio-Aufbereitung", self._prepare_audio),
            ("Untertitel-Aufbereitung", self._prepare_subtitles),
            ("STEP 7/7 Final-Mux", self._mux_final_output),
        )
        for stage_label, stage in stages:
            if stage(state, runner):
                continue
            if not self._temp_state.failure_reason:
                self._temp_state.record_failure(reason=f"{stage_label} fehlgeschlagen", stage=stage_label)
            elif not self._temp_state.failure_stage:
                self._temp_state.failure_stage = stage_label
            return DVPipelineResult(
                False,
                tuple(state.sidecar_paths),
                self._temp_state.failure_reason,
                self._temp_state.failure_stage or stage_label,
            )

        target_container = str(getattr(request, "container", "mp4") or "mp4").lower()
        if any_sidecar_export_enabled(getattr(self, "_subtitle_rules", {}), container=target_container):
            export_result = self._subtitle_service.export_sidecars_result(
                input_path=request.input_path,
                output_base=Path(request.output_path).with_suffix(""),
                media_info=request.media_info,
                file_override=request.override,
                container=target_container,
            )
            state.sidecar_paths = list(export_result.exported_paths)
            if not export_result.complete:
                reason = export_result.failure_summary() or "Sidecar-Export unvollstaendig."
                self._temp_state.record_failure(reason=reason, stage="Untertitel-Export")
                self._log(f"❌ [DV] {reason}", "error")
                return DVPipelineResult(False, tuple(state.sidecar_paths), reason, "Untertitel-Export")
        else:
            state.sidecar_paths = []
            if getattr(request.media_info, "subtitle_streams", None):
                self._log(
                    "ℹ️  [DV] MKV-Ziel: ausgewählte Untertitel sind im Container gespeichert; "
                    "kein externer Sidecar-Export.",
                    "info",
                )

        output = Path(request.output_path)
        success = output.exists() and output.stat().st_size > 0
        if not success:
            self._temp_state.record_failure(
                reason="STEP 7/7 Final-Mux: Ausgabedatei fehlt oder ist leer",
                stage="STEP 7/7 Final-Mux",
            )
        return DVPipelineResult(
            success,
            tuple(state.sidecar_paths),
            "" if success else self._temp_state.failure_reason,
            "" if success else self._temp_state.failure_stage,
            verified_hdr10plus=bool(success and state.verified_hdr10plus),
            verified_dolby_vision=bool(success and state.verified_dolby_vision),
        )

    # Dünne Kompatibilitäts-Delegationen. Keine eigene Fachlogik ergänzen.
    def _extract_source_hevc(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        return _video_service(self).extract_source_hevc(state, runner)

    def _convert_profile_to_81(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        return _video_service(self).convert_profile_to_81(state, runner)

    def _extract_rpu(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        return _video_service(self).extract_rpu(state, runner)

    def _reconcile_crop_from_rpu(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        return _video_service(self).reconcile_crop_from_rpu(state, runner)

    def _encode_video(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        return _video_service(self).encode_video(state, runner)

    def _cleanup_burn_sub(self, request) -> None:
        _video_service(self).cleanup_burn_sub(request)

    def _resolve_rpu_crop(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        return _metadata_service(self).resolve_rpu_crop(
            state,
            runner,
            save_crop_failure=self._save_crop_failure,
        )

    def _save_crop_failure(self, state: DVPipelineState, runner: DVCommandRunner, *, level5_proc=None) -> Path:
        return _metadata_service(self).save_crop_failure(
            state,
            runner,
            mux_plain_mp4_without_dv=self._mux_plain_mp4_without_dv,
            level5_proc=level5_proc,
        )

    def _mux_plain_mp4_without_dv(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        return _metadata_service(self).mux_plain_mp4_without_dv(state, runner)

    def _inject_dynamic_metadata(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        return _metadata_service(self).inject_dynamic_metadata(
            state,
            runner,
            validate_rpu_frame_parity=self._validate_rpu_frame_parity,
            verify_injected_rpu=self._verify_injected_rpu,
        )

    def _validate_rpu_frame_parity(
        self,
        runner: DVCommandRunner,
        *,
        rpu_path: Path,
        hevc_path: Path,
    ) -> bool:
        return _metadata_service(self).validate_rpu_frame_parity(
            runner,
            rpu_path=rpu_path,
            hevc_path=hevc_path,
            probe_rpu_frame_count=self._probe_rpu_frame_count,
            probe_hevc_frame_count=self._probe_hevc_frame_count,
        )

    def _probe_rpu_frame_count(self, runner: DVCommandRunner, path: Path) -> int | None:
        return _metadata_service(self).probe_rpu_frame_count(runner, path)

    def _probe_hevc_frame_count(self, runner: DVCommandRunner, path: Path) -> int | None:
        return _metadata_service(self).probe_hevc_frame_count(runner, path)

    def _verify_injected_rpu(
        self,
        runner: DVCommandRunner,
        *,
        injected_hevc: Path,
        expected_rpu: Path,
        scratch_rpu: Path,
    ) -> bool:
        return _metadata_service(self).verify_injected_rpu(
            runner,
            injected_hevc=injected_hevc,
            expected_rpu=expected_rpu,
            scratch_rpu=scratch_rpu,
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        return DVDynamicMetadataService.sha256(path)

    def _prepare_audio(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        return _mux_service(self).prepare_audio(state, runner)

    def _prepare_subtitles(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        return _mux_service(self).prepare_subtitles(state, runner)

    def _mux_final_output(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        return _mux_service(self).mux_final_output(
            state,
            runner,
            verify_final_mux_metadata=self._verify_final_mux_metadata,
        )

    def _verify_final_mux_metadata(self, state: DVPipelineState, runner: DVCommandRunner) -> bool:
        return _mux_service(self).verify_final_mux_metadata(
            state,
            runner,
            inspect_dynamic_hdr=inspect_dynamic_hdr_with_mediainfo,
            verify_fallback=self._verify_final_mux_metadata_fallback,
        )

    def _verify_final_mux_metadata_fallback(
        self,
        state: DVPipelineState,
        runner: DVCommandRunner,
        *,
        verify_dv: bool,
        verify_hdr10plus: bool,
    ) -> bool:
        return _mux_service(self).verify_final_mux_metadata_fallback(
            state,
            runner,
            verify_dv=verify_dv,
            verify_hdr10plus=verify_hdr10plus,
            sha256_file=self._sha256,
        )
