# -*- coding: utf-8 -*-
"""Runtime-Service-Aufbau für :class:`ConverterThread`.

Der QThread bleibt die öffentliche Fassade. Dieses Modul übernimmt ausschließlich
jenen Bootstrap, der erst im Worker-Thread nach dem Speichern der Einstellungen
erfolgen darf: Toolpfade laden, laufzeitabhängige Services erzeugen und den
ConversionWorkflowRunner verdrahten.
"""
from __future__ import annotations

import inspect
import json
import sys

from ..core.paths import get_tool_paths
from ..core.settings import (
    DEFAULT_OUTPUT_DURATION_MAX_EXTRA_S,
    DEFAULT_OUTPUT_DURATION_MAX_PERCENT,
    DEFAULT_OUTPUT_DURATION_MIN_PERCENT,
    DEFAULT_OUTPUT_MIN_SIZE_KB,
    DEFAULT_REPAIR_DURATION_REMUX_ENABLED,
    DEFAULT_REPAIR_DURATION_TIMESTAMP_ENABLED,
    SET_KEY_OUTPUT_DURATION_MAX_EXTRA_S,
    SET_KEY_OUTPUT_DURATION_MAX_PERCENT,
    SET_KEY_OUTPUT_DURATION_MIN_PERCENT,
    SET_KEY_OUTPUT_MIN_SIZE_KB,
    SET_KEY_REPAIR_DURATION_REMUX_ENABLED,
    SET_KEY_REPAIR_DURATION_TIMESTAMP_ENABLED,
    settings_bool,
    settings_int,
)
from .av1_metadata_pipeline import AV1DolbyVisionPipeline, AV1HDR10PlusPipeline
from .duration_repair_service import DurationRepairService
from .dv_processing_pipeline import DVProcessingPipeline
from .dv_runtime_models import DVEncoderConfig
from .hdrplus_conversion import HDRPlusConversionHelper
from .media_analysis_service import MediaAnalysisService
from .output_verifier import OutputVerifier
from .postprocess_service import AsyncPostProcessCoordinator, PostProcessService
from .source_visual_check import SourceVisualCheckService
from .standard_pipeline_runner import StandardPipelineRunner
from .workflow_engine import ConversionWorkflowRunner
from .workflow_factory import build_workflow_services


class ConverterRuntimeBuilder:
    """Erzeugt die laufzeitabhängigen Converter-Services im Worker-Thread."""

    def __init__(self, worker) -> None:
        self._worker = worker

    def initialize(self) -> None:
        self._load_tools_and_write_debug_header()
        self._build_pipeline_services()
        self._build_workflow()

    def _load_tools_and_write_debug_header(self) -> None:
        worker = self._worker
        services = worker._services
        job = worker._job_state
        import dragontools.worker.converter_progress as converter_progress_module
        import dragontools.worker.dv_level5_editor as dv_level5_editor_module
        import dragontools.worker.dv_processing_pipeline as dv_processing_pipeline_module

        # Absichtlich erst im Worker-Thread laden: Settings können unmittelbar vor
        # QThread.start() noch geändert worden sein.
        services.tools = get_tool_paths()
        worker._verbose_logger.write(f"[DEBUG] sys.executable: {sys.executable}")
        try:
            worker_source = inspect.getsourcefile(worker.__class__) or inspect.getfile(worker.__class__)
        except (OSError, TypeError):
            worker_source = "<unbekannt>"
        worker._verbose_logger.write(
            f"[DEBUG] converter_thread loaded from: {worker_source}"
        )
        worker._verbose_logger.write(
            f"[DEBUG] dv_processing_pipeline loaded from: {dv_processing_pipeline_module.__file__}"
        )
        worker._verbose_logger.write(
            f"[DEBUG] dv_level5_editor loaded from: {dv_level5_editor_module.__file__}"
        )
        worker._verbose_logger.write(
            f"[DEBUG] converter_progress loaded from: {converter_progress_module.__file__}"
        )
        worker._verbose_logger.write(
            f"[DEBUG] normal log file: {worker.log_file_path or '-'}"
        )
        try:
            encoder_options_debug = json.dumps(
                job.encoder_options,
                ensure_ascii=False,
                sort_keys=True,
            )
        except Exception:
            encoder_options_debug = repr(job.encoder_options)
        worker._verbose_logger.write(
            f"[DEBUG] initial encoder options: {encoder_options_debug}"
        )

    def _build_pipeline_services(self) -> None:
        worker = self._worker
        job = worker._job_state
        services = worker._services
        tools = services.tools
        if tools is None:
            raise RuntimeError("Converter-Toolpfade wurden nicht initialisiert.")

        services.hdrplus = HDRPlusConversionHelper(
            tools=tools,
            log=worker.log,
            codec=job.codec,
            crf=job.crf,
            preset=job.preset,
            encoder_options=job.encoder_options,
            progress_runner=services.progress,
            temp_state=worker._temp_state,
            subtitle_rules=job.subtitle_rules,
        )

        min_size_kb = settings_int(
            worker.settings,
            SET_KEY_OUTPUT_MIN_SIZE_KB,
            DEFAULT_OUTPUT_MIN_SIZE_KB,
            minimum=1,
            maximum=102400,
        )
        duration_min_percent = settings_int(
            worker.settings,
            SET_KEY_OUTPUT_DURATION_MIN_PERCENT,
            DEFAULT_OUTPUT_DURATION_MIN_PERCENT,
            minimum=1,
            maximum=100,
        )
        duration_max_percent = settings_int(
            worker.settings,
            SET_KEY_OUTPUT_DURATION_MAX_PERCENT,
            DEFAULT_OUTPUT_DURATION_MAX_PERCENT,
            minimum=100,
            maximum=1000,
        )
        duration_max_extra_s = settings_int(
            worker.settings,
            SET_KEY_OUTPUT_DURATION_MAX_EXTRA_S,
            DEFAULT_OUTPUT_DURATION_MAX_EXTRA_S,
            minimum=0,
            maximum=3600,
        )
        services.output_verifier = OutputVerifier(
            ffprobe_path=tools.ffprobe,
            min_size_bytes=min_size_kb * 1024,
            duration_min_ratio=duration_min_percent / 100.0,
            duration_max_ratio=duration_max_percent / 100.0,
            duration_max_extra_s=duration_max_extra_s,
        )
        services.duration_repair = DurationRepairService(
            mkvmerge_path=tools.mkvmerge,
            mp4box_path=tools.mp4box,
            ffmpeg_path=tools.ffmpeg,
            ffprobe_path=tools.ffprobe,
            mediainfo_path=tools.mediainfo,
            output_verifier=services.output_verifier,
            log=worker.log,
            normal_remux_enabled=settings_bool(
                worker.settings,
                SET_KEY_REPAIR_DURATION_REMUX_ENABLED,
                DEFAULT_REPAIR_DURATION_REMUX_ENABLED,
            ),
            timestamp_repair_enabled=settings_bool(
                worker.settings,
                SET_KEY_REPAIR_DURATION_TIMESTAMP_ENABLED,
                DEFAULT_REPAIR_DURATION_TIMESTAMP_ENABLED,
            ),
            worker=worker,
        )
        services.media_analysis = MediaAnalysisService(
            tools=tools,
            probe_duration_ms=services.progress.probe_ms,
            log=worker.log,
        )
        services.standard_pipeline = StandardPipelineRunner(
            tools=tools,
            codec=job.codec,
            crf=job.crf,
            preset=job.preset,
            encoder_options=job.encoder_options,
            progress_runner=services.progress.run_p,
            log=worker.log,
            subtitle_rules=job.subtitle_rules,
            worker=worker,
        )
        services.av1_dv_pipeline = AV1DolbyVisionPipeline(
            tools=tools,
            progress_runner=services.progress.run_p,
            temp_state=worker._temp_state,
            log=worker.log,
            subtitle_rules=job.subtitle_rules,
            worker=worker,
        )
        services.av1_hdrplus_pipeline = AV1HDR10PlusPipeline(
            tools=tools,
            progress_runner=services.progress.run_p,
            temp_state=worker._temp_state,
            log=worker.log,
            subtitle_rules=job.subtitle_rules,
            worker=worker,
        )
        services.postprocess = PostProcessService(
            settings=worker.settings,
            tools=tools,
            log=worker.log,
            worker=worker,
        )
        services.postprocess_coordinator = AsyncPostProcessCoordinator(
            settings=worker.settings,
            tools=tools,
            log=worker.log,
            worker=worker,
        )
        services.source_visual_check = SourceVisualCheckService(
            ffmpeg_path=tools.ffmpeg,
            ffprobe_path=tools.ffprobe,
        )
        services.dv_pipeline = DVProcessingPipeline(
            tools=tools,
            encoder_config=DVEncoderConfig(
                codec=job.codec,
                crf=job.crf,
                preset=job.preset,
                options=job.encoder_options,
            ),
            progress_runner=services.progress,
            subtitle_rules=job.subtitle_rules,
            temp_state=worker._temp_state,
            log=worker.log,
            verbose_logger=worker._verbose_logger,
            worker=worker,
        )

    def _build_workflow(self) -> None:
        worker = self._worker
        services = worker._services
        services.workflow_services = build_workflow_services(
            services=services,
            job=worker._job_state,
            runtime_state=worker._runtime_state,
            temp_state=worker._temp_state,
            session_state=worker._session_state,
            logger=worker._logger,
        )
        services.workflow_runner = ConversionWorkflowRunner(
            services.workflow_services,
            replace_original=worker._job_state.overwrite_original,
        )
