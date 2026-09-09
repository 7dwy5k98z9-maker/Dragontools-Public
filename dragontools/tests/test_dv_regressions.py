# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


def _make_sub(index, codec, language, forced=False):
    return SimpleNamespace(index=index, codec=codec, language=language, forced=forced, title="")


def _make_mi(subs):
    return SimpleNamespace(subtitle_streams=subs, audio_streams=[])


def test_dv_auto_exportiert_keep_subs_als_sidecars(tmp_path):
    from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService

    svc = SubtitleSidecarService(
        ffmpeg_path="/fake/ffmpeg",
        subtitle_rules={
            "dv_extract_external_subs": True,
            "keep_rules": {
                "keep_forced": True,
                "keep_all_german": True,
                "keep_german_if_no_burn": False,
                "keep_english_fallback": False,
            },
        },
        log=lambda *_: None,
    )
    mi = _make_mi([
        _make_sub(3, "subrip", "deu", forced=False),
        _make_sub(4, "ass", "eng", forced=False),
    ])

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_text("subtitle", encoding="utf-8")
        return MagicMock(returncode=0, stderr=b"")

    with patch(
        "dragontools.worker.subtitle_sidecar_service.run_tool",
        side_effect=fake_run,
    ) as mock_run:
        result = svc.export_sidecars_result(
            input_path="/src/input.mkv",
            output_base=tmp_path / "Film",
            media_info=mi,
        )

    assert result.complete is True
    assert len(result.exported_paths) == 1
    mapped = [call.args[0][call.args[0].index("-map") + 1] for call in mock_run.call_args_list]
    assert mapped == ["0:3"]


def test_dv_custom_export_respektiert_keep_auswahl(tmp_path):
    from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService

    svc = SubtitleSidecarService(
        ffmpeg_path="/fake/ffmpeg",
        subtitle_rules={
            "dv_extract_external_subs": True,
        },
        log=lambda *_: None,
    )
    mi = _make_mi([
        _make_sub(3, "subrip", "deu", forced=False),
        _make_sub(4, "ass", "eng", forced=False),
    ])

    def fake_run(cmd, **kwargs):
        Path(cmd[-1]).write_text("subtitle", encoding="utf-8")
        return MagicMock(returncode=0, stderr=b"")

    with patch(
        "dragontools.worker.subtitle_sidecar_service.run_tool",
        side_effect=fake_run,
    ) as mock_run:
        result = svc.export_sidecars_result(
            input_path="/src/input.mkv",
            output_base=tmp_path / "Film",
            media_info=mi,
            file_override={
                "subtitle_mode": "custom",
                "subtitle_tracks": [
                    {"index": 4, "keep": True, "burn_in": False},
                ],
            },
        )

    assert result.complete is True
    assert len(result.exported_paths) == 1
    mapped = [call.args[0][call.args[0].index("-map") + 1] for call in mock_run.call_args_list]
    assert mapped == ["0:4"]


def test_dv_sidecars_werden_nach_replace_zum_finalen_stem_verschoben(tmp_path, monkeypatch):
    from dragontools.worker.workflow_services import WorkflowServices

    src_dir = tmp_path / "src"
    temp_dir = src_dir / "__temp_overwrite__"
    src_dir.mkdir()
    temp_dir.mkdir()

    temp_video = temp_dir / "Film.mp4"
    final_video = src_dir / "Film.mp4"
    temp_sidecar = temp_dir / "Film.de.srt"
    temp_sidecar.write_text("1\n00:00:00,000 --> 00:00:01,000\nText\n", encoding="utf-8")

    from dragontools.worker import workflow_output_commit as workflow_module
    from dragontools.worker.workflow_output_commit import WorkflowOutputCommitCoordinator

    original_start = workflow_module.SidecarJournal.start
    monkeypatch.setattr(
        workflow_module.SidecarJournal,
        "start",
        classmethod(lambda _cls, **kwargs: original_start(root=tmp_path, **kwargs)),
    )

    sidecar_outputs = {}
    commit = WorkflowOutputCommitCoordinator(
        replace_service=object(),
        logger=SimpleNamespace(info=lambda *_: None, warn=lambda *_: None, error=lambda *_: None),
        result_service=object(),
        sidecar_outputs=sidecar_outputs,
        postprocess_outputs=None,
    )
    ctx = SimpleNamespace(
        input_path=str(src_dir / "Film.mkv"),
        output_path=str(temp_video),
        final_output_path=str(final_video),
        sidecar_paths=[str(temp_sidecar)],
    )

    commit.finalize_sidecars(ctx)

    final_sidecar = src_dir / "Film.de.srt"
    assert final_sidecar.exists()
    assert not temp_sidecar.exists()
    assert ctx.sidecar_paths == [str(final_sidecar)]
    assert sidecar_outputs[ctx.input_path] == [str(final_sidecar)]


def test_dv_level5_editor_nutzt_keinen_autocrop_fallback(tmp_path):
    from dragontools.worker.dv_level5_editor import DVLevel5Editor

    rpu_orig = tmp_path / "metadata.rpu"
    rpu_orig.write_bytes(b"rpu")
    rpu_final = tmp_path / "metadata_final.rpu"
    edit_json = tmp_path / "level5.json"
    media_info = SimpleNamespace(
        primary_video=SimpleNamespace(width=3840, height=2160)
    )
    calls = []

    def run_cmd(cmd, **kwargs):
        calls.append(cmd)
        return SimpleNamespace(returncode=1)

    editor = DVLevel5Editor(dovi_tool_path="dovi_tool", log=lambda *_: None)
    result = editor.resolve_rpu_for_crop(
        run_cmd,
        crop="crop=3840:1600:0:280",
        media_info=media_info,
        rpu_orig=rpu_orig,
        rpu_final=rpu_final,
        edit_json=edit_json,
        save_failure_artifacts=lambda *_: tmp_path,
    )

    assert result is None
    assert len(calls) == 1


def test_hdr10plus_bitstream_service_extract_inject_und_verify(tmp_path):
    from dragontools.worker.hdr10plus_bitstream_service import HDR10PlusBitstreamService

    calls = []
    source = tmp_path / "source.hevc"
    encoded = tmp_path / "encoded.hevc"
    injected = tmp_path / "injected.hevc"
    meta = tmp_path / "metadata.json"
    verify = tmp_path / "verify.json"
    source.write_bytes(b"s" * 2048)
    encoded.write_bytes(b"e" * 2048)

    def run_cmd(cmd, allow_error=False):
        calls.append(list(cmd))
        if cmd[1] == "extract":
            out = Path(cmd[cmd.index("-o") + 1])
            out.write_text('{"metadata": [1]}', encoding="utf-8")
        elif cmd[1] == "inject":
            out = Path(cmd[cmd.index("-o") + 1])
            out.write_bytes(b"h" * 2048)
        return 0

    svc = HDR10PlusBitstreamService(
        hdr10plus_tool_path="hdr10plus_tool",
        log=lambda *_: None,
    )

    assert svc.extract_metadata(run_cmd, source_stream=source, output_json=meta) is True
    assert svc.inject_metadata(
        run_cmd,
        input_hevc=encoded,
        metadata_json=meta,
        output_hevc=injected,
    ) is True
    assert svc.verify_metadata(run_cmd, source_stream=injected, scratch_json=verify) is True

    assert calls[0][:3] == ["hdr10plus_tool", "extract", str(source)]
    assert calls[1][:4] == ["hdr10plus_tool", "inject", "-i", str(encoded)]
    assert calls[2][:3] == ["hdr10plus_tool", "extract", str(injected)]
    assert not verify.exists()


def test_workflow_reicht_hdr10plus_erhalt_ueber_typed_request_an_dv_pipeline_weiter():
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.dv_workflow_pipeline_adapter import DVPipelineExecutorAdapter
    from dragontools.worker.workflow_models import PipelineExecutionRequest

    captured = {}

    class Pipeline:
        last_sidecar_paths = []
        last_failure_reason = ""
        last_failure_stage = ""
        last_tool_output = ""

        def configure_encoder(self, config):
            self.encoder_config = config

        def run(self, **kwargs):
            captured.update(kwargs)
            return True

    pipeline = Pipeline()
    temp_state = DVTempState()
    adapter = DVPipelineExecutorAdapter(pipeline, temp_state)
    request = PipelineExecutionRequest(
        pipeline="dv",
        input_path="/in.mkv",
        output_path="/out.mp4",
        container="mp4",
        media_info=SimpleNamespace(),
        plan=SimpleNamespace(
            vf_args=[],
            audio_args=[],
            audio_input_args=[],
            sn=[],
            burn_sub_or_vf=False,
            crop=None,
        ),
        override={},
        strip_only=False,
        duration_ms=1000,
        codec="h265",
        crf=23,
        preset="p6",
        encoder_options={"encoder": "nvenc"},
        preserve_hdrplus=True,
    )

    result = adapter.execute(request)

    assert result.success is True
    assert captured["preserve_hdrplus"] is True
    assert pipeline.encoder_config.codec == "h265"
    assert pipeline.encoder_config.options == {"encoder": "nvenc"}


def test_converter_hat_keine_dv_hdrplus_legacy_wrapper_mehr():
    converter_source = (PACKAGE_ROOT / "worker" / "converter_thread.py").read_text(encoding="utf-8")
    factory_source = (PACKAGE_ROOT / "worker" / "workflow_factory.py").read_text(encoding="utf-8")

    assert "def _convert_dv(" not in converter_source
    assert "def _convert_hdrplus(" not in converter_source
    assert "DVPipelineExecutorAdapter(services.dv_pipeline, temp_state)" in factory_source
    assert "hdrplus_pipeline=services.hdrplus" in factory_source


def test_dv_command_runner_sichert_toolfehler_fuer_errorreport(monkeypatch):
    from dragontools.worker.dv_command_runner import DVCommandRunner
    from dragontools.worker.dv_runtime_models import DVTempState

    state = DVTempState()

    def fake_run(command, **kwargs):
        from dragontools.worker.tool_runner import ToolRunResult
        return ToolRunResult(command=list(command), returncode=17, stdout="", stderr="konkreter toolfehler")

    monkeypatch.setattr("dragontools.worker.dv_command_runner.run_tool", fake_run)
    runner = DVCommandRunner(
        log=lambda *_: None,
        verbose_log=lambda *_: None,
        no_window_kwargs=lambda: {},
        temp_state=state,
    )

    rc = runner.run(["dovi_tool", "inject-rpu"], label="STEP 6/7 RPU-Injektion")

    assert rc == 17
    assert state.failure_stage == "STEP 6/7 RPU-Injektion"
    assert "dovi_tool fehlgeschlagen (rc=17)" in state.failure_reason
    assert state.last_tool == "dovi_tool"
    assert "inject-rpu" in state.last_command
    assert state.stderr == "konkreter toolfehler"


def test_dv_pipeline_uebernimmt_stufenfehler_in_oeffentliche_diagnose(tmp_path):
    from dragontools.worker.dv_pipeline_context import DVPipelineResult
    from dragontools.worker.dv_processing_pipeline import DVProcessingPipeline
    from dragontools.worker.dv_runtime_models import DVEncoderConfig, DVTempState

    pipeline = DVProcessingPipeline(
        tools=SimpleNamespace(
            ffmpeg="ffmpeg",
            ffprobe="ffprobe",
            mp4box="MP4Box",
            dovi_tool="dovi_tool",
            hdr10plus_tool="hdr10plus_tool",
        ),
        encoder_config=DVEncoderConfig(
            codec="h265", crf=21, preset="medium", options={"encoder": "cpu"}
        ),
        progress_runner=SimpleNamespace(),
        subtitle_rules={},
        temp_state=DVTempState(),
        log=lambda *_: None,
    )
    pipeline._build_stages = lambda: SimpleNamespace(
        run=lambda *_: DVPipelineResult(
            False,
            (),
            "RPU-Injektion fehlgeschlagen",
            "STEP 6/7 RPU-Injektion",
        )
    )
    mi = SimpleNamespace(
        dv_profile_major=8,
        dv_profile="8",
        has_dv=True,
        has_hdrplus=False,
    )

    ok = pipeline.run(
        str(tmp_path / "in.mkv"),
        str(tmp_path / "out.mp4"),
        mi,
        [], [], None, [], None,
    )

    assert ok is False
    assert pipeline.last_failure_reason == "RPU-Injektion fehlgeschlagen"
    assert pipeline.last_failure_stage == "STEP 6/7 RPU-Injektion"


def test_error_report_enthaelt_pipeline_diagnose(tmp_path, monkeypatch):
    from dragontools.core import error_report

    monkeypatch.setattr(error_report, "resolve_log_month_dir", lambda _log: tmp_path)
    ctx = SimpleNamespace(
        input_path=str(tmp_path / "film.mkv"),
        pipeline="dv",
        container="mp4",
        strategy_name="dv",
        replace_original=True,
        strip_only=False,
        pipeline_failure_reason="MP4Box fehlgeschlagen (rc=1)",
        pipeline_failure_stage="STEP 7/7 MP4Box-Mux",
        pipeline_failure_tool="MP4Box.exe",
        pipeline_failure_command='MP4Box.exe -new "film.mp4"',
    )

    path = error_report.write_conversion_error_report(
        ctx=ctx,
        reason="Pipeline-Ausführung fehlgeschlagen (dv): STEP 7/7 MP4Box-Mux",
        tool_output="mux error",
    )
    text = Path(path).read_text(encoding="utf-8")

    assert "Pipeline-Diagnose" in text
    assert "Fehlerstufe: STEP 7/7 MP4Box-Mux" in text
    assert "Tool: MP4Box.exe" in text
    assert 'Kommando: MP4Box.exe -new "film.mp4"' in text
    assert "mux error" in text


def test_dv_pipeline_stage_builder_ist_vollstaendig_verdrahtet():
    """Regression: das Stages-Refactoring darf keine Builder-Methode verlieren."""
    from dragontools.worker.dv_pipeline_stages import DVPipelineStages
    from dragontools.worker.dv_processing_pipeline import DVProcessingPipeline
    from dragontools.worker.dv_runtime_models import DVEncoderConfig, DVTempState

    temp_state = DVTempState()
    pipeline = DVProcessingPipeline(
        tools=SimpleNamespace(
            ffmpeg="ffmpeg",
            ffprobe="ffprobe",
            mp4box="MP4Box",
            dovi_tool="dovi_tool",
            hdr10plus_tool="hdr10plus_tool",
        ),
        encoder_config=DVEncoderConfig(
            codec="h265", crf=21, preset="medium", options={"encoder": "cpu"}
        ),
        progress_runner=SimpleNamespace(),
        subtitle_rules={},
        temp_state=temp_state,
        log=lambda *_: None,
    )

    stages = pipeline._build_stages()

    assert isinstance(stages, DVPipelineStages)
    assert stages._temp_state is temp_state
    assert stages._tools is pipeline._tools
    assert stages._audio_mux_service is pipeline._audio_mux_service
    assert stages._rpu_service is pipeline._rpu_service
    assert stages._assert_nonempty_file.__self__ is pipeline
    assert stages._clear_burn_sub_tmp.__self__ is pipeline


def test_dv_pipeline_dateivalidierung_liefert_konkrete_diagnose(tmp_path):
    from dragontools.worker.dv_processing_pipeline import DVProcessingPipeline
    from dragontools.worker.dv_runtime_models import DVEncoderConfig, DVTempState

    state = DVTempState(last_tool="ffmpeg.exe", last_command="ffmpeg.exe -i in.mkv")
    pipeline = DVProcessingPipeline(
        tools=SimpleNamespace(
            ffmpeg="ffmpeg",
            ffprobe="ffprobe",
            mp4box="MP4Box",
            dovi_tool="dovi_tool",
            hdr10plus_tool="hdr10plus_tool",
        ),
        encoder_config=DVEncoderConfig(
            codec="h265", crf=21, preset="medium", options={"encoder": "cpu"}
        ),
        progress_runner=SimpleNamespace(),
        subtitle_rules={},
        temp_state=state,
        log=lambda *_: None,
    )

    missing = tmp_path / "missing.hevc"
    assert pipeline._assert_nonempty_file(missing, "STEP Test") is False
    assert state.failure_stage == "STEP Test"
    assert "Erwartete Datei fehlt" in state.failure_reason
    assert state.last_tool == "ffmpeg.exe"
    assert state.last_command == "ffmpeg.exe -i in.mkv"


def _make_dv_stage_test_context(tmp_path, *, profile=8, has_hdrplus=True, transfer="PQ", primaries="BT.2020"):
    from dragontools.worker.dv_pipeline_context import DVRunRequest, DVPipelineState, DVWorkFiles
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.dv_pipeline_stages import DVPipelineStages

    mi = SimpleNamespace(
        dv_profile_major=profile,
        dv_profile=str(profile),
        has_dv=True,
        has_hdrplus=has_hdrplus,
        transfer_characteristics=transfer,
        color_primaries=primaries,
        primary_video=SimpleNamespace(color_transfer=transfer, color_primaries=primaries),
    )
    request = DVRunRequest.create(
        input_path="in.mkv",
        output_path=str(tmp_path / "out.mp4"),
        media_info=mi,
        vf_args=[],
        audio_args=[],
        audio_input_args=None,
        sn=[],
        crop=None,
        override=None,
        preserve_hdrplus=has_hdrplus,
    )
    tmp_path.mkdir(parents=True, exist_ok=True)
    files = DVWorkFiles.create(tmp_path)
    files.src_hevc.write_bytes(b"source")
    temp_state = DVTempState()
    logs = []
    rpu_inputs = []

    class RpuService:
        def extract_rpu(self, _run, *, input_hevc, output_rpu):
            rpu_inputs.append(input_hevc)
            output_rpu.write_bytes(b"rpu")
            return True

    stages = DVPipelineStages(
        tools=SimpleNamespace(dovi_tool="dovi_tool", ffmpeg="ffmpeg"),
        encoder_config=SimpleNamespace(),
        progress_runner=SimpleNamespace(),
        temp_state=temp_state,
        audio_mux_service=SimpleNamespace(),
        mp4box_muxer=SimpleNamespace(),
        rpu_service=RpuService(),
        hdr10plus_service=SimpleNamespace(),
        level5_editor=SimpleNamespace(),
        subtitle_service=SimpleNamespace(),
        failure_recovery=SimpleNamespace(),
        log=lambda msg, level="info": logs.append((level, msg)),
        verbose_log=lambda msg: None,
        assert_nonempty_file=lambda path, _label: path.exists() and path.stat().st_size > 0,
        clear_burn_sub_tmp=lambda: None,
    )
    return stages, DVPipelineState(request=request, files=files), temp_state, logs, rpu_inputs


def test_dv_p8_hdr10_basis_laeuft_wie_altstand_durch_mode2(tmp_path):
    stages, state, temp_state, logs, _ = _make_dv_stage_test_context(tmp_path)
    calls = []

    class Runner:
        def run(self, cmd, **kwargs):
            calls.append((list(cmd), kwargs))
            state.files.p8_hevc.write_bytes(b"converted-p8")
            return 0

    assert stages._convert_profile_to_81(state, Runner()) is True
    assert state.profile_hevc == state.files.p8_hevc
    assert calls == [
        (
            [
                "dovi_tool", "-m", "2", "convert",
                "--discard", str(state.files.src_hevc),
                "-o", str(state.files.p8_hevc),
            ],
            {
                "timeout": calls[0][1]["timeout"],
                "label": "STEP 2/7 DV-Profilkonvertierung",
            },
        )
    ]
    assert temp_state.failure_reason == ""
    assert any("dovi_tool -m 2" in msg for _, msg in logs)


def test_dv_p8_pq_bt2020_ohne_hdr10plus_flag_wird_trotzdem_mode2_normalisiert(tmp_path):
    stages, state, _temp_state, _logs, _ = _make_dv_stage_test_context(
        tmp_path,
        profile=8,
        has_hdrplus=False,
        transfer="PQ",
        primaries="BT.2020",
    )
    calls = []

    class Runner:
        def run(self, cmd, **kwargs):
            calls.append(list(cmd))
            state.files.p8_hevc.write_bytes(b"converted-p8")
            return 0

    assert stages._convert_profile_to_81(state, Runner()) is True
    assert calls[0][1:4] == ["-m", "2", "convert"]
    assert state.profile_hevc == state.files.p8_hevc


def test_dv_p8_rpu_extraktion_verwendet_mode2_output(tmp_path):
    stages, state, _temp_state, _logs, rpu_inputs = _make_dv_stage_test_context(tmp_path)
    state.files.p8_hevc.write_bytes(b"converted-p8")
    state.profile_hevc = state.files.p8_hevc

    class Runner:
        def adapter(self, **_kwargs):
            return lambda *_args, **_kw: 0

    assert stages._extract_rpu(state, Runner()) is True
    assert rpu_inputs == [state.files.p8_hevc]

def test_dv_unknown_metadata_fallback_nicht_fuer_p7_oder_hlg_p8(tmp_path):
    for profile, has_hdrplus, transfer, primaries in (
        (7, True, "PQ", "BT.2020"),
        (8, False, "HLG", "BT.2020"),
    ):
        stages, state, temp_state, _logs, _ = _make_dv_stage_test_context(
            tmp_path / f"case_{profile}_{transfer}",
            profile=profile,
            has_hdrplus=has_hdrplus,
            transfer=transfer,
            primaries=primaries,
        )

        class Runner:
            def run(self, *_args, **_kwargs):
                temp_state.record_failure(
                    reason="convert failed",
                    stage="STEP 2/7 DV-Profilkonvertierung",
                    tool="dovi_tool.exe",
                    command="dovi_tool -m 2 convert",
                    output="Error: CM v4.0 - Unknown metadata block found: Level 253, length 2",
                )
                return 1

        assert stages._convert_profile_to_81(state, Runner()) is False
        assert state.profile_hevc is None


def test_dv_command_runner_kennzeichnet_unbekannten_cmv4_block_als_toolinkompatibilitaet(monkeypatch):
    from dragontools.worker.dv_command_runner import DVCommandRunner
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.tool_runner import ToolRunResult

    temp_state = DVTempState()
    monkeypatch.setattr(
        "dragontools.worker.dv_command_runner.run_tool",
        lambda command, **_kwargs: ToolRunResult(
            command=list(command),
            returncode=1,
            stdout="",
            stderr="Error: CM v4.0 - Unknown metadata block found: Level 253, length 2",
        ),
    )
    runner = DVCommandRunner(
        log=lambda *_: None,
        verbose_log=lambda *_: None,
        no_window_kwargs=lambda: {},
        temp_state=temp_state,
    )

    assert runner.run(["dovi_tool", "extract-rpu"], label="RPU") == 1
    assert "Profilnormalisierung" in temp_state.failure_reason
    assert "Level 253" in temp_state.stderr


def test_dv_combo_erkennt_has_hdr10plus_alias_ohne_has_hdrplus():
    """Regression: MediaInfo-Pfade dürfen HDR10+ nicht wegen Feldnamensdrift verlieren."""
    from dragontools.worker.dv_pipeline_context import DVRunRequest

    mi = SimpleNamespace(
        dv_profile_major=8,
        dv_profile="8",
        has_dv=True,
        has_hdrplus=False,
        has_hdr10plus=True,
    )
    req = DVRunRequest.create(
        input_path="in.mkv",
        output_path="out.mp4",
        media_info=mi,
        vf_args=[],
        audio_args=[],
        audio_input_args=None,
        sn=[],
        crop=None,
        override=None,
        preserve_hdrplus=True,
    )

    assert req.preserve_dv_hdr10plus_combo is True


def test_hdr10plus_service_entfernt_stale_outputs_vor_toollauf(tmp_path):
    from dragontools.worker.hdr10plus_bitstream_service import HDR10PlusBitstreamService

    source = tmp_path / "source.hevc"
    encoded = tmp_path / "encoded.hevc"
    meta = tmp_path / "metadata.json"
    injected = tmp_path / "injected.hevc"
    source.write_bytes(b"s" * 2048)
    encoded.write_bytes(b"e" * 2048)
    meta.write_text('{"SceneInfo": [{"SceneFirstFrameIndex": 0}]}', encoding="utf-8")
    injected.write_bytes(b"stale" * 300)

    seen = {}

    def fail_inject(cmd, allow_error=False):
        seen["output_missing_before_run"] = not injected.exists()
        return 1

    svc = HDR10PlusBitstreamService(hdr10plus_tool_path="hdr10plus_tool", log=lambda *_: None)
    assert svc.inject_metadata(
        fail_inject,
        input_hevc=encoded,
        metadata_json=meta,
        output_hevc=injected,
    ) is False
    assert seen["output_missing_before_run"] is True
    assert not injected.exists()


def test_hdr10plus_finalcheck_vergleicht_metadaten_mit_quelle(tmp_path):
    from dragontools.worker.hdr10plus_bitstream_service import HDR10PlusBitstreamService

    source = tmp_path / "final.hevc"
    expected = tmp_path / "source.json"
    scratch = tmp_path / "verify.json"
    source.write_bytes(b"s" * 2048)
    expected.write_text(
        '{"SceneInfo": [{"SceneFirstFrameIndex": 0, "LuminanceParameters": {"AverageRGB": 10}}], '
        '"ToolInfo": {"Version": "source"}}',
        encoding="utf-8",
    )

    def extract_changed(cmd, allow_error=False):
        out = Path(cmd[cmd.index("-o") + 1])
        out.write_text(
            '{"SceneInfo": [{"SceneFirstFrameIndex": 0, "LuminanceParameters": {"AverageRGB": 99}}], '
            '"ToolInfo": {"Version": "verify"}}',
            encoding="utf-8",
        )
        return 0

    logs = []
    svc = HDR10PlusBitstreamService(
        hdr10plus_tool_path="hdr10plus_tool",
        log=lambda msg, level="info": logs.append((level, msg)),
    )
    assert svc.verify_metadata(
        extract_changed,
        source_stream=source,
        scratch_json=scratch,
        expected_json=expected,
    ) is False
    assert not scratch.exists()
    assert any("weichen von der Quelle ab" in msg for _, msg in logs)


def test_hdr10plus_finalcheck_ignoriert_nur_toolinfo(tmp_path):
    from dragontools.worker.hdr10plus_bitstream_service import HDR10PlusBitstreamService

    source = tmp_path / "final.hevc"
    expected = tmp_path / "source.json"
    scratch = tmp_path / "verify.json"
    source.write_bytes(b"s" * 2048)
    expected.write_text(
        '{"SceneInfo": [{"SceneFirstFrameIndex": 0}], "ToolInfo": {"Version": "old"}}',
        encoding="utf-8",
    )

    def extract_same(cmd, allow_error=False):
        out = Path(cmd[cmd.index("-o") + 1])
        out.write_text(
            '{"SceneInfo": [{"SceneFirstFrameIndex": 0}], "ToolInfo": {"Version": "new"}}',
            encoding="utf-8",
        )
        return 0

    svc = HDR10PlusBitstreamService(hdr10plus_tool_path="hdr10plus_tool", log=lambda *_: None)
    assert svc.verify_metadata(
        extract_same,
        source_stream=source,
        scratch_json=scratch,
        expected_json=expected,
    ) is True
    assert not scratch.exists()



def test_workflow_sidecar_finalisierung_sichert_vorhandenes_sidecar(tmp_path, monkeypatch):
    from dragontools.worker.workflow_services import WorkflowServices

    stage = tmp_path / "__temp_overwrite__"
    stage.mkdir()
    generated = stage / "Film.de.srt"
    generated.write_text("GENERATED", encoding="utf-8")
    existing = tmp_path / "Film.de.srt"
    existing.write_text("USER", encoding="utf-8")

    from dragontools.worker import workflow_output_commit as workflow_module
    from dragontools.worker.workflow_output_commit import WorkflowOutputCommitCoordinator

    original_start = workflow_module.SidecarJournal.start
    monkeypatch.setattr(
        workflow_module.SidecarJournal,
        "start",
        classmethod(lambda _cls, **kwargs: original_start(root=tmp_path, **kwargs)),
    )

    logs = []
    commit = WorkflowOutputCommitCoordinator(
        replace_service=object(),
        logger=SimpleNamespace(
            info=lambda msg: logs.append(("info", msg)),
            warn=lambda msg: logs.append(("warn", msg)),
            error=lambda msg: logs.append(("error", msg)),
        ),
        result_service=object(),
        sidecar_outputs={},
        postprocess_outputs=None,
    )
    ctx = SimpleNamespace(
        input_path=str(tmp_path / "Film.mkv"),
        output_path=str(stage / "Film.mp4"),
        final_output_path=str(tmp_path / "Film.mp4"),
        sidecar_paths=[str(generated)],
    )

    commit.finalize_sidecars(ctx)

    assert existing.read_text(encoding="utf-8") == "GENERATED"
    backups = list(tmp_path.glob("Film.de.srt.dragontools_backup*"))
    assert len(backups) == 1
    assert backups[0].read_text(encoding="utf-8") == "USER"
    assert any("gesichert" in msg for level, msg in logs if level == "warn")


def test_dv_pipeline_blockiert_unvollstaendigen_sidecar_export(tmp_path):
    from dragontools.worker.dv_pipeline_stages import DVPipelineStages
    from dragontools.worker.subtitle_sidecar_service import (
        SubtitleExportFailure,
        SubtitleExportResult,
    )

    output = tmp_path / "Film.mp4"
    output.write_bytes(b"video")

    class TempState:
        failure_reason = ""
        failure_stage = ""
        def record_failure(self, *, reason, stage, **kwargs):
            self.failure_reason = reason
            self.failure_stage = stage

    temp_state = TempState()
    export_result = SubtitleExportResult(
        planned_stream_indices=(3,),
        exported_paths=(),
        failures=(
            SubtitleExportFailure(3, "de", "subrip", "ffmpeg rc=1"),
        ),
    )
    stages = DVPipelineStages.__new__(DVPipelineStages)
    stages._audio_mux_service = SimpleNamespace(build_audio_meta=lambda *args: [])
    stages._subtitle_service = SimpleNamespace(
        export_sidecars_result=lambda **kwargs: export_result
    )
    stages._temp_state = temp_state
    stages._log = lambda *_: None
    stages._vlog = lambda *_: None
    stages._extract_source_hevc = lambda *args: True
    stages._convert_profile_to_81 = lambda *args: True
    stages._extract_rpu = lambda *args: True
    stages._encode_video = lambda *args: True
    stages._resolve_rpu_crop = lambda *args: True
    stages._inject_dynamic_metadata = lambda *args: True
    stages._prepare_audio = lambda *args: True
    stages._mux_final_output = lambda *args: True

    request = SimpleNamespace(
        media_info=SimpleNamespace(),
        override={},
        input_path=str(tmp_path / "source.mkv"),
        output_path=str(output),
        crop=None,
        preserve_dv_hdr10plus_combo=False,
    )
    state = SimpleNamespace(request=request, audio_meta=[], sidecar_paths=[])

    result = stages.run(state, SimpleNamespace())

    assert result.success is False
    assert result.failure_stage == "Untertitel-Export"
    assert "0/1" in result.failure_reason


def test_dv_adapter_propagates_pipeline_verified_dolby_vision():
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.dv_workflow_pipeline_adapter import DVPipelineExecutorAdapter
    from dragontools.worker.workflow_models import PipelineExecutionRequest

    class Pipeline:
        last_sidecar_paths = []
        last_dolby_vision_verified = True
        last_failure_reason = ""
        last_failure_stage = ""
        last_tool_output = ""

        def configure_encoder(self, config):
            self.encoder_config = config

        def run(self, **kwargs):
            return True

    request = PipelineExecutionRequest(
        pipeline="dv", input_path="in.mkv", output_path="out.mp4", container="mp4",
        media_info=SimpleNamespace(),
        plan=SimpleNamespace(vf_args=[], audio_args=[], audio_input_args=[], sn=[], burn_sub_or_vf=False, crop=None),
        override={}, strip_only=False, duration_ms=1000, codec="h265", crf=23,
        preset="p6", encoder_options={"encoder": "nvenc"}, preserve_hdrplus=False,
    )

    result = DVPipelineExecutorAdapter(Pipeline(), DVTempState()).execute(request)

    assert result.success is True
    assert result.verified_dolby_vision is True


def test_dv_adapter_propagates_pipeline_verified_hdr10plus():
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.dv_workflow_pipeline_adapter import DVPipelineExecutorAdapter
    from dragontools.worker.workflow_models import PipelineExecutionRequest

    class Pipeline:
        last_sidecar_paths = []
        last_hdr10plus_verified = True
        last_dolby_vision_verified = True
        last_failure_reason = ""
        last_failure_stage = ""
        last_tool_output = ""

        def configure_encoder(self, config):
            self.encoder_config = config

        def run(self, **kwargs):
            return True

    request = PipelineExecutionRequest(
        pipeline="dv", input_path="in.mkv", output_path="out.mp4", container="mp4",
        media_info=SimpleNamespace(),
        plan=SimpleNamespace(vf_args=[], audio_args=[], audio_input_args=[], sn=[], burn_sub_or_vf=False, crop=None),
        override={}, strip_only=False, duration_ms=1000, codec="h265", crf=23,
        preset="p6", encoder_options={"encoder": "nvenc"}, preserve_hdrplus=True,
    )

    result = DVPipelineExecutorAdapter(Pipeline(), DVTempState()).execute(request)

    assert result.success is True
    assert result.verified_hdr10plus is True
    assert result.verified_dolby_vision is True


def test_dv_post_mux_prueft_hdr10plus_und_rpu_aus_finalem_mp4(tmp_path):
    from dragontools.worker.dv_pipeline_stages import DVPipelineStages
    from dragontools.worker.dv_runtime_models import DVTempState

    expected_rpu = tmp_path / "expected.rpu"
    expected_rpu.write_bytes(b"RPU" * 1024)
    expected_hdr = tmp_path / "metadata_hdr10plus.json"
    expected_hdr.write_text('{"SceneInfo":[{"SceneFirstFrameIndex":0}]}', encoding="utf-8")
    output = tmp_path / "out.mp4"
    output.write_bytes(b"MP4" * 1024)

    class Runner:
        def run(self, command, **kwargs):
            Path(command[-1]).write_bytes(b"HEVC" * 1024)
            return 0

        def adapter(self, **kwargs):
            return lambda *args, **kw: 0

    class RpuService:
        def extract_rpu(self, run_fn, *, input_hevc, output_rpu):
            assert input_hevc.name == "final_mux_verify.hevc"
            output_rpu.write_bytes(expected_rpu.read_bytes())
            return True

    seen = {}

    class HdrService:
        def verify_metadata(self, run_fn, *, source_stream, scratch_json, expected_json):
            seen["source"] = source_stream
            seen["expected"] = expected_json
            return True

    stages = DVPipelineStages(
        tools=SimpleNamespace(ffmpeg="ffmpeg"), encoder_config=None, progress_runner=None,
        temp_state=DVTempState(), audio_mux_service=None, mp4box_muxer=None,
        rpu_service=RpuService(), hdr10plus_service=HdrService(), level5_editor=None,
        subtitle_service=None, failure_recovery=None, log=lambda *_: None,
        verbose_log=lambda *_: None,
        assert_nonempty_file=lambda path, _label: path.exists() and path.stat().st_size > 0,
        clear_burn_sub_tmp=lambda: None,
    )
    state = SimpleNamespace(
        request=SimpleNamespace(output_path=str(output), preserve_dv_hdr10plus_combo=True),
        files=SimpleNamespace(root=tmp_path, hdr10plus_json=expected_hdr),
        rpu_to_use=expected_rpu,
        verified_hdr10plus=False,
        verified_dolby_vision=False,
    )

    assert stages._verify_final_mux_metadata(state, Runner()) is True
    assert state.verified_dolby_vision is True
    assert state.verified_hdr10plus is True
    assert seen["source"].name == "final_mux_verify.hevc"
    assert seen["expected"] == expected_hdr


def test_dv_final_verify_uses_mediainfo_as_primary_and_skips_bitstream_fallback(tmp_path, monkeypatch):
    from dragontools.worker.dv_pipeline_stages import DVPipelineStages
    from dragontools.worker.dv_runtime_models import DVTempState
    import dragontools.worker.dv_pipeline_stages as stages_module

    output = tmp_path / "out.mp4"
    output.write_bytes(b"MP4" * 1024)
    logs = []

    monkeypatch.setattr(
        stages_module,
        "inspect_dynamic_hdr_with_mediainfo",
        lambda *_args, **_kwargs: SimpleNamespace(
            conclusive=True,
            dolby_vision=True,
            dolby_vision_profile="8",
            hdr10plus=True,
            warnings=(),
        ),
    )

    class Runner:
        def run(self, *_args, **_kwargs):
            raise AssertionError("Bitstream-Fallback darf bei positivem MediaInfo nicht laufen")

        def adapter(self, **_kwargs):
            raise AssertionError("Tool-Fallback darf bei positivem MediaInfo nicht laufen")

    stages = DVPipelineStages(
        tools=SimpleNamespace(ffmpeg="ffmpeg"), encoder_config=None, progress_runner=None,
        temp_state=DVTempState(), audio_mux_service=None, mp4box_muxer=None,
        rpu_service=None, hdr10plus_service=None, level5_editor=None,
        subtitle_service=None, failure_recovery=None,
        log=lambda msg, level: logs.append((level, msg)), verbose_log=lambda *_: None,
        assert_nonempty_file=lambda path, _label: path.exists() and path.stat().st_size > 0,
        clear_burn_sub_tmp=lambda: None,
    )
    state = SimpleNamespace(
        request=SimpleNamespace(output_path=str(output), preserve_dv_hdr10plus_combo=True),
        files=SimpleNamespace(root=tmp_path), rpu_to_use=None,
        verified_hdr10plus=False, verified_dolby_vision=False,
    )

    assert stages._verify_final_mux_metadata(state, Runner()) is True
    assert state.verified_dolby_vision is True
    assert state.verified_hdr10plus is True
    assert any("Finales MP4: Dolby Vision JA" in msg for _level, msg in logs)
    assert any("HDR10+ JA" in msg for _level, msg in logs)


def test_dv_final_verify_fallback_checks_only_hdr10plus_when_mediainfo_confirms_dv(tmp_path, monkeypatch):
    from dragontools.worker.dv_pipeline_stages import DVPipelineStages
    from dragontools.worker.dv_runtime_models import DVTempState
    import dragontools.worker.dv_pipeline_stages as stages_module

    output = tmp_path / "out.mp4"
    output.write_bytes(b"MP4" * 1024)
    expected_hdr = tmp_path / "metadata_hdr10plus.json"
    expected_hdr.write_text('{"SceneInfo":[{"SceneFirstFrameIndex":0}]}', encoding="utf-8")

    monkeypatch.setattr(
        stages_module,
        "inspect_dynamic_hdr_with_mediainfo",
        lambda *_args, **_kwargs: SimpleNamespace(
            conclusive=True,
            dolby_vision=True,
            dolby_vision_profile="8",
            hdr10plus=False,
            warnings=(),
        ),
    )

    class Runner:
        def run(self, command, **_kwargs):
            Path(command[-1]).write_bytes(b"HEVC" * 1024)
            return 0

        def adapter(self, **_kwargs):
            return lambda *args, **kw: 0

    class RpuService:
        def extract_rpu(self, *_args, **_kwargs):
            raise AssertionError("DV-Fallback darf nicht laufen, wenn MediaInfo DV bestätigt")

    seen = {}

    class HdrService:
        def verify_metadata(self, _run_fn, *, source_stream, scratch_json, expected_json):
            seen["source"] = source_stream
            seen["expected"] = expected_json
            return True

    stages = DVPipelineStages(
        tools=SimpleNamespace(ffmpeg="ffmpeg"), encoder_config=None, progress_runner=None,
        temp_state=DVTempState(), audio_mux_service=None, mp4box_muxer=None,
        rpu_service=RpuService(), hdr10plus_service=HdrService(), level5_editor=None,
        subtitle_service=None, failure_recovery=None, log=lambda *_: None,
        verbose_log=lambda *_: None,
        assert_nonempty_file=lambda path, _label: path.exists() and path.stat().st_size > 0,
        clear_burn_sub_tmp=lambda: None,
    )
    state = SimpleNamespace(
        request=SimpleNamespace(output_path=str(output), preserve_dv_hdr10plus_combo=True),
        files=SimpleNamespace(root=tmp_path, hdr10plus_json=expected_hdr),
        rpu_to_use=None, verified_hdr10plus=False, verified_dolby_vision=False,
    )

    assert stages._verify_final_mux_metadata(state, Runner()) is True
    assert state.verified_dolby_vision is True
    assert state.verified_hdr10plus is True
    assert seen["source"].name == "final_mux_verify.hevc"
    assert seen["expected"] == expected_hdr


def test_final_mediainfo_hdr_inspection_reads_dv_and_hdr10plus_without_ffprobe(monkeypatch):
    import dragontools.core.media_analyzer as analyzer

    payload = {
        "media": {
            "track": [
                {"@type": "General", "Format": "MPEG-4"},
                {
                    "@type": "Video",
                    "HDR_Format": "Dolby Vision, Version 1.0, Profile 8.1, dvhe.08.06, BL+RPU / SMPTE ST 2094 App 4",
                    "HDR_Format_Profile": "dvhe.08.06",
                    "HDR_Format_Compatibility": "HDR10+ / HDR10",
                    "HDR_Format_String": "Dolby Vision / HDR10+",
                },
            ]
        }
    }
    monkeypatch.setattr(
        analyzer,
        "_run_mediainfo_json",
        lambda *_args, **_kwargs: (payload, [], True),
    )

    result = analyzer.inspect_dynamic_hdr_with_mediainfo(
        "final.mp4", SimpleNamespace(mediainfo="MediaInfo.exe")
    )

    assert result.conclusive is True
    assert result.dolby_vision is True
    assert result.dolby_vision_profile == "8"
    assert result.hdr10plus is True


def test_dv_adapter_drops_stale_sidecars_on_failed_run():
    from dragontools.worker.dv_runtime_models import DVTempState
    from dragontools.worker.dv_workflow_pipeline_adapter import DVPipelineExecutorAdapter
    from dragontools.worker.workflow_models import PipelineExecutionRequest

    class Pipeline:
        last_sidecar_paths = ["old-job.de.srt"]
        last_hdr10plus_verified = False
        last_dolby_vision_verified = False
        last_failure_reason = "preflight failed"
        last_failure_stage = "DV-Preflight"
        last_tool_output = ""

        def configure_encoder(self, config):
            self.encoder_config = config

        def run(self, **kwargs):
            return False

    request = PipelineExecutionRequest(
        pipeline="dv", input_path="in.mkv", output_path="out.mp4", container="mp4",
        media_info=SimpleNamespace(),
        plan=SimpleNamespace(vf_args=[], audio_args=[], audio_input_args=[], sn=[], burn_sub_or_vf=False, crop=None),
        override={}, strip_only=False, duration_ms=1000, codec="h265", crf=23,
        preset="p6", encoder_options={"encoder": "nvenc"}, preserve_hdrplus=False,
    )

    result = DVPipelineExecutorAdapter(Pipeline(), DVTempState()).execute(request)

    assert result.success is False
    assert result.sidecar_paths == ()


def test_dv_pipeline_reset_clears_previous_run_sidecars():
    from dragontools.tests.test_dv_pipeline_architecture import _make_pipeline_for_preflight

    pipeline, _logs = _make_pipeline_for_preflight(codec="h265")
    pipeline.last_sidecar_paths = ["previous.de.srt"]

    pipeline._reset_run_diagnostics()

    assert pipeline.last_sidecar_paths == []
