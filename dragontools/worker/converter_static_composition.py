# -*- coding: utf-8 -*-
"""Startzeit-unabhängige Composition Root für ``ConverterThread``.

Nur Services, die bereits im GUI/Main-Thread sicher aufgebaut werden dürfen,
werden hier erzeugt. Toolpfad- und pipelineabhängige Services verbleiben im
``ConverterRuntimeBuilder`` und werden erst in ``QThread.run()`` aufgebaut.
"""
from __future__ import annotations

from .archive_service import ArchiveService
from .cleanup_service import CleanupService
from .converter_detection import ConverterDetectionHelper
from .converter_progress import ConverterProgressHelper
from .converter_stream_args import ConverterStreamArgsHelper
from .converter_strip import ConverterStripHelper
from .encode_plan_service import EncodePlanService
from .output_path_service import OutputPathService
from .pipeline_decision_service import PipelineDecisionService
from .replace_service import ReplaceService
from .worker_result_service import WorkerConversionResultService
from .converter_thread_state import ConverterServiceRegistry


def build_static_converter_services(
    worker,
    *,
    job,
    settings,
    logger,
    runtime_state,
    failure_details: dict[str, dict],
) -> ConverterServiceRegistry:
    """Erzeugt die stabilen Services mit expliziten Datenabhängigkeiten."""
    services = ConverterServiceRegistry()
    services.progress = ConverterProgressHelper(worker)
    services.detection = ConverterDetectionHelper(worker)
    services.stream_args = ConverterStreamArgsHelper(worker)
    services.strip = ConverterStripHelper(worker)

    services.archive = ArchiveService(log=worker.log)
    services.pipeline_decision = PipelineDecisionService(
        codec=job.codec,
        encoder_options=job.encoder_options,
        file_overrides=job.file_overrides,
        settings=settings,
        logger=logger,
        archive_service=services.archive,
    )
    services.output_paths = OutputPathService(
        codec=job.codec,
        overwrite_original=job.overwrite_original,
    )
    services.replace = ReplaceService(
        overwrite_original=job.overwrite_original,
        log=worker.log,
    )
    services.cleanup = CleanupService(
        overwrite_original=job.overwrite_original,
        temp_overwrite_dir=services.output_paths.temp_overwrite_dir,
        log=worker.log,
    )
    services.encode_plan = EncodePlanService(
        codec=job.codec,
        encoder_options=job.encoder_options,
        scale_mode=job.scale_mode,
        detect_imax_auto=services.detection.detect_imax_auto,
        detect_crop=services.detection.detect_crop,
        probe_duration_ms=services.progress.probe_ms,
        stream_args_helper=services.stream_args,
        log=worker.log,
        logger=logger,
    )
    services.result = WorkerConversionResultService(
        logger=logger,
        runtime_state=runtime_state,
        overwrite_original=job.overwrite_original,
        event_emit=worker.event.emit,
        file_progress_emit=worker.file_progress.emit,
        file_result_emit=worker.file_result.emit,
        log=worker.log,
        failure_details=failure_details,
    )
    return services
