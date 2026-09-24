# -*- coding: utf-8 -*-
"""Per-file policy and transaction dispatch for :mod:`dv_remux_thread`."""
from __future__ import annotations

import time
import traceback
from pathlib import Path

from ..core.media_analyzer import analyze_media
from .converter_utils import _fd, _fs
from .dv_remux_job import DVRemuxJobRunner
from .dv_remux_policy import decide_dv_remux
from .dv_result_contract import emit_dv_failure, mark_dv_terminal
from .worker_events import progress_event, result_event


class DVRemuxFileDispatcher:
    """Keep profile-policy and one-file dispatch outside the QThread facade."""

    def __init__(self, worker) -> None:
        self.worker = worker

    def prepare_metadata(self, input_path: str):
        w = self.worker
        name = Path(input_path).name
        media_info = analyze_media(input_path, w.tools)
        for warning in getattr(media_info, "analysis_warnings", []) or []:
            w.log(f"Analyse-Warnung: {warning}", "warn")
        dur_ms = w._process_runner.probe_ms(input_path)
        return name, media_info, dur_ms, w.file_overrides.get(input_path)

    def emit_success(
        self,
        input_path: str,
        output_path: str,
        name: str,
        size_before: int,
        start_ts: float,
    ) -> None:
        w = self.worker
        size_after = Path(output_path).stat().st_size if Path(output_path).exists() else 0
        duration = time.time() - start_ts
        w.log(
            f"✅ {name} → {Path(output_path).name} | "
            f"{_fs(size_before)} → {_fs(size_after)} | {_fd(duration)}",
            "success",
        )
        w.file_progress.emit(input_path, 100, None)
        w.worker_event.emit(progress_event(input_path, 100, None))
        mark_dv_terminal(w, input_path, "✅")
        w.worker_event.emit(result_event(input_path, output_path, "✅"))
        w.file_result.emit(input_path, output_path, "✅")

    def run(self, input_path: str) -> bool:
        w = self.worker
        try:
            # Go through the public compatibility hook so older tests/extensions
            # that replace ``_prepare_remux_metadata`` keep working.
            prepared = w.prepare_remux_metadata(input_path)
        except Exception as exc:
            w.log(f"❌ Medienanalyse für DV-Remux fehlgeschlagen: {Path(input_path).name}", "error")
            w.log(traceback.format_exc(), "error")
            emit_dv_failure(
                w, input_path, f"Medienanalyse für DV-Remux fehlgeschlagen: {exc}",
                stage="analysis"
            )
            return False

        _name, media_info, _dur_ms, _file_override = prepared
        decision = decide_dv_remux(
            media_info,
            container=w.container,
            keep_dv7_mkv=w.keep_dv7_mkv,
            encode_dv5=w.encode_dv5,
        )
        if decision.should_skip:
            w.log(f"⏭️ {Path(input_path).name}: {decision.reason}", "warn")
            w.file_progress.emit(input_path, 100, None)
            w.worker_event.emit(progress_event(input_path, 100, None))
            mark_dv_terminal(w, input_path, "⏭️")
            w.worker_event.emit(result_event(input_path, input_path, "⏭️"))
            w.file_result.emit(input_path, input_path, "⏭️")
            return False
        if decision.should_encode:
            w.log(f"⚠️ {Path(input_path).name}: {decision.reason}", "warn")
            return w._dv5_fallback.run(input_path)

        job = DVRemuxJobRunner(
            w,
            process_runner=w._process_runner,
            pipeline=w._mp4box_pipeline,
            output_manager=w._output_manager,
            subtitle_service=w._subtitle_service,
            prepare_metadata=lambda _path: prepared,
            emit_success=lambda *args: w.emit_remux_success(*args),
        )
        return job.run(input_path)
