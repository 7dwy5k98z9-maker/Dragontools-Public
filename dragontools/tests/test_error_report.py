from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def test_error_report_writes_context_and_tool_output(tmp_path):
    from dragontools.core.error_report import write_conversion_error_report
    from dragontools.worker.workflow_engine import WorkflowVerifyResult

    primary_video = SimpleNamespace(
        codec="hevc",
        width=3840,
        height=2160,
        bit_depth=10,
        pix_fmt="yuv420p10le",
        hdr_format="dolby_vision",
        color_space="bt2020nc",
        color_transfer="smpte2084",
        color_primaries="bt2020",
    )
    analysis = SimpleNamespace(
        path=str(tmp_path / "film.mkv"),
        primary_video=primary_video,
        audio_streams=[object()],
        subtitle_streams=[object(), object()],
        is_hdr=True,
        dolby_vision=True,
        has_hdrplus=False,
        dolby_vision_profile="7",
        analysis_source="ffprobe + MediaInfo",
        analysis_warnings=["Testwarnung"],
    )
    ctx = SimpleNamespace(
        input_path=str(tmp_path / "film.mkv"),
        analysis=analysis,
        duration_ms=123_000,
        size_before=4096,
        pipeline="dv",
        container="mp4",
        strategy_name="dv",
        base_dir=tmp_path,
        output_path=str(tmp_path / "film.mp4"),
        final_output_path="",
        sidecar_paths=[str(tmp_path / "film.de.srt")],
        replace_original=True,
        effective_codec="h265",
        effective_crf=23,
        effective_preset="p6",
        effective_scale_mode="source",
        effective_encoder_options={"encoder": "nvenc"},
        encoder_profile_label="UHD",
        file_override={"encoder_profile": {"codec": "h265"}},
        verify_result=WorkflowVerifyResult(
            exists=True,
            size_ok=True,
            container_ok=False,
            messages=["Container passt nicht"],
        ),
        duration_repair_attempted=True,
        duration_after_ffmpeg_s=4_296_408.0,
        duration_after_remux_s=4_296_408.0,
        duration_after_timestamp_fix_s=1441.56,
        duration_repair_method="timestamp",
        duration_repair_reason="Timestamp-Reparatur erfolgreich.",
        duration_repair_ffmpeg_cmd=["ffmpeg", "-c", "copy", "-bsf:v:0", "setts=pts=N*1001/24000/TB"],
        duration_repair_timing_summary=["Framerate: 24000/1001", "Videoframes: 34563"],
    )

    report = write_conversion_error_report(
        ctx=ctx,
        reason="Pipeline-Ausfuehrung fehlgeschlagen (dv)",
        tool_output="dovi_tool: failed",
        log_file=tmp_path / "run.txt",
        traceback_text="Traceback test",
    )

    text = Path(report).read_text(encoding="utf-8")
    assert "DragonTools Fehlerbericht" in text
    assert "Pipeline: dv" in text
    assert "DV Profil 7" in text
    assert "Container passt nicht" in text
    assert "Methode: timestamp" in text
    assert "Dauer nach Timestamp-Fix: 1441.6s" in text
    assert "setts=pts=N*1001/24000/TB" in text
    assert "Framerate: 24000/1001" in text
    assert "dovi_tool: failed" in text


def test_worker_result_service_stores_failure_details(tmp_path):
    from dragontools.worker.worker_result_service import WorkerConversionResultService

    runtime = SimpleNamespace(fehlgeschlagen=0)
    events = []
    file_results = []
    logs = []
    details = {}
    service = WorkerConversionResultService(
        logger=SimpleNamespace(),
        runtime_state=runtime,
        overwrite_original=True,
        event_emit=events.append,
        file_progress_emit=lambda *args: None,
        file_result_emit=lambda *args: file_results.append(args),
        log=lambda msg, level="info": logs.append((msg, level)),
        failure_details=details,
    )
    ctx = SimpleNamespace(
        input_path=str(tmp_path / "kaputt.mkv"),
        pipeline="standard",
        container="mkv",
        strategy_name="standard",
        error_report_path=str(tmp_path / "report.txt"),
    )

    service.fail(ctx, "ffmpeg meldet Fehler")

    assert runtime.fehlgeschlagen == 1
    assert details[ctx.input_path]["message"] == "ffmpeg meldet Fehler"
    assert details[ctx.input_path]["error_report"].endswith("report.txt")
    assert details[ctx.input_path]["pipeline"] == "standard"
    assert file_results


def test_worker_result_service_blocked_size_policy_is_not_success(tmp_path):
    from dragontools.worker.worker_result_service import WorkerConversionResultService

    source = tmp_path / "film.mkv"
    archived = tmp_path / "Archiv" / "film.mkv"
    archived.parent.mkdir()
    source.write_bytes(b"original" * 100)
    archived.write_bytes(b"encoded" * 200)

    runtime = SimpleNamespace(fehlgeschlagen=0, erfolgreich=0, total_before=0, total_after=0)
    events = []
    file_results = []
    logs = []
    details = {}
    service = WorkerConversionResultService(
        logger=SimpleNamespace(),
        runtime_state=runtime,
        overwrite_original=True,
        event_emit=events.append,
        file_progress_emit=lambda *args: None,
        file_result_emit=lambda *args: file_results.append(args),
        log=lambda msg, level="info": logs.append((msg, level)),
        failure_details=details,
    )
    ctx = SimpleNamespace(
        input_path=str(source),
        final_output_path=str(archived),
        replacement_archived_path=str(archived),
        replacement_block_reason="Ausgabedatei ist größer als erlaubt; Original wurde nicht ersetzt.",
        pipeline="standard",
        container="mkv",
        strategy_name="standard",
        size_before=source.stat().st_size,
    )

    service.finalize_blocked(ctx)

    assert runtime.erfolgreich == 0
    assert runtime.fehlgeschlagen == 1
    assert file_results[-1] == (str(source), str(archived), "\u26a0\ufe0f")
    assert details[str(source)]["message"].startswith("Ausgabedatei ist größer")
    assert any("Original nicht ersetzt" in msg for msg, level in logs if level == "warn")
