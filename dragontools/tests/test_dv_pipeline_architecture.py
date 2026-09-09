# -*- coding: utf-8 -*-
from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
from types import SimpleNamespace

from dragontools.core.media_hdr_detection import choose_dovi_convert_mode
from dragontools.worker.dv_encode_command import build_dv_encode_command
from dragontools.worker.dv_pipeline_context import DVRunRequest, normalize_dv_profile_major
from dragontools.worker.dv_runtime_models import DVEncoderConfig


def _enc_cfg() -> DVEncoderConfig:
    return DVEncoderConfig(
        codec="h265",
        crf=21,
        preset="medium",
        options={"encoder": "cpu"},
    )


def test_profile_major_normalisierung_deckt_p5_p7_p8_und_string_cachewerte_ab():
    for raw, expected in ((5, 5), ("5", 5), (7, 7), ("7", 7), (8, 8), ("8", 8)):
        mi = SimpleNamespace(dv_profile_major=raw, dv_profile=str(raw))
        assert normalize_dv_profile_major(mi) == expected


def test_dovi_convert_mode_ist_fuer_p5_auch_bei_string_mode_3():
    assert choose_dovi_convert_mode(SimpleNamespace(dv_profile_major=5)) == "3"
    assert choose_dovi_convert_mode(SimpleNamespace(dv_profile_major="5")) == "3"
    assert choose_dovi_convert_mode(SimpleNamespace(dv_profile_major=7)) == "2"
    assert choose_dovi_convert_mode(SimpleNamespace(dv_profile_major="8")) == "2"


def test_p5_encode_verwendet_originalcontainer_libplacebo_und_nicht_p8_stream(tmp_path):
    p8 = tmp_path / "p8.hevc"
    out = tmp_path / "encoded.hevc"
    plan = build_dv_encode_command(
        ffmpeg_path="ffmpeg",
        encoder_config=_enc_cfg(),
        input_path="film.mkv",
        p8_hevc=p8,
        output_hevc=out,
        vf_args=["-map", "0:v:0", "-vf", "scale=1920:-2"],
        profile_major=5,
    )

    joined = " ".join(map(str, plan.command))
    assert plan.uses_libplacebo is True
    assert plan.video_source == "film.mkv"
    assert str(p8) not in plan.command
    assert "libplacebo=" in joined
    assert plan.command.count("-i") == 1
    assert plan.command[plan.command.index("-i") + 1] == "film.mkv"
    assert "-f" in plan.command and "hevc" in plan.command


def test_p5_filter_complex_behält_original_input_und_setzt_libplacebo_vor_userfilter(tmp_path):
    plan = build_dv_encode_command(
        ffmpeg_path="ffmpeg",
        encoder_config=_enc_cfg(),
        input_path="film.mkv",
        p8_hevc=tmp_path / "p8.hevc",
        output_hevc=tmp_path / "encoded.hevc",
        vf_args=[
            "-filter_complex",
            "[0:v:0]crop=3840:1600:0:280[vout]",
            "-map", "[vout]",
        ],
        profile_major=5,
    )
    fc = plan.command[plan.command.index("-filter_complex") + 1]
    assert fc.startswith("[0:v:0]libplacebo=")
    assert "crop=3840:1600:0:280" in fc
    assert "[vout]" in fc


def test_p7_und_p8_encode_verwenden_p8_hevc_als_videoquelle(tmp_path):
    for profile in (7, 8):
        p8 = tmp_path / f"p8_{profile}.hevc"
        plan = build_dv_encode_command(
            ffmpeg_path="ffmpeg",
            encoder_config=_enc_cfg(),
            input_path="film.mkv",
            p8_hevc=p8,
            output_hevc=tmp_path / f"encoded_{profile}.hevc",
            vf_args=["-map", "0:v:0", "-vf", "scale=1920:-2"],
            profile_major=profile,
        )
        joined = " ".join(map(str, plan.command))
        assert plan.uses_libplacebo is False
        assert plan.video_source == str(p8)
        assert str(p8) in plan.command
        assert plan.command.count("-i") == 2
        assert "libplacebo=" not in joined
        map_positions = [i for i, value in enumerate(plan.command) if value == "-map"]
        assert any(plan.command[i + 1] == "1:v:0" for i in map_positions)


def test_p7_filter_complex_wird_auf_input1_remapped_ohne_zweiten_videomap(tmp_path):
    p8 = tmp_path / "p8.hevc"
    plan = build_dv_encode_command(
        ffmpeg_path="ffmpeg",
        encoder_config=_enc_cfg(),
        input_path="film.mkv",
        p8_hevc=p8,
        output_hevc=tmp_path / "encoded.hevc",
        vf_args=[
            "-filter_complex",
            "[0:v:0]crop=3840:1600:0:280[vout]",
            "-map", "[vout]",
        ],
        profile_major=7,
    )
    fc = plan.command[plan.command.index("-filter_complex") + 1]
    assert "[1:v:0]" in fc
    assert "[0:v:0]" not in fc
    map_targets = [plan.command[i + 1] for i, v in enumerate(plan.command[:-1]) if v == "-map"]
    assert "[vout]" in map_targets
    assert "1:v:0" not in map_targets


def test_request_p5_string_wird_als_p5_sonderpfad_markiert():
    mi = SimpleNamespace(
        dv_profile_major="5",
        dv_profile="5",
        has_dv=True,
        has_hdrplus=False,
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
        preserve_hdrplus=False,
    )
    assert req.is_p5 is True
    assert req.profile_major == 5


def test_dv_pipeline_run_ist_nur_noch_orchestrator_und_stufen_bleiben_begrenzt():
    pipeline_path = PACKAGE_ROOT / "worker" / "dv_processing_pipeline.py"
    stages_path = PACKAGE_ROOT / "worker" / "dv_pipeline_stages.py"
    pipeline_tree = ast.parse(pipeline_path.read_text(encoding="utf-8"))
    stages_tree = ast.parse(stages_path.read_text(encoding="utf-8"))

    pipeline_cls = next(
        node for node in pipeline_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DVProcessingPipeline"
    )
    run_node = next(
        node for node in pipeline_cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "run"
    )
    assert run_node.end_lineno - run_node.lineno + 1 <= 110
    assert len(pipeline_path.read_text(encoding="utf-8").splitlines()) <= 330

    stages_cls = next(
        node for node in stages_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DVPipelineStages"
    )
    stage_methods = [node for node in stages_cls.body if isinstance(node, ast.FunctionDef)]
    assert max(node.end_lineno - node.lineno + 1 for node in stage_methods) <= 80


def test_produktiver_p5_run_hat_keinen_legacy_remux_aufruf():
    source = (PACKAGE_ROOT / "worker" / "dv_processing_pipeline.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    pipeline_cls = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DVProcessingPipeline"
    )
    run_node = next(
        node for node in pipeline_cls.body
        if isinstance(node, ast.FunctionDef) and node.name == "run"
    )
    called_attrs = {
        node.func.attr
        for node in ast.walk(run_node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "_run_p5_remux" not in called_attrs
    assert "_libplacebo_available" in called_attrs


def test_legacy_p5_remux_kompatibilitaetspfad_ist_entfernt():
    pipeline_path = PACKAGE_ROOT / "worker" / "dv_processing_pipeline.py"
    legacy_path = PACKAGE_ROOT / "worker" / "dv_p5_legacy_remux.py"
    level5_path = PACKAGE_ROOT / "worker" / "dv_level5_editor.py"

    assert not legacy_path.exists()

    pipeline_tree = ast.parse(pipeline_path.read_text(encoding="utf-8"))
    pipeline_cls = next(
        node for node in pipeline_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DVProcessingPipeline"
    )
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "_run_p5_remux"
        for node in pipeline_cls.body
    )

    level5_tree = ast.parse(level5_path.read_text(encoding="utf-8"))
    level5_cls = next(
        node for node in level5_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "DVLevel5Editor"
    )
    assert not any(
        isinstance(node, ast.FunctionDef) and node.name == "edit_rpu_for_crop"
        for node in level5_cls.body
    )


def _make_pipeline_for_preflight(*, codec="h265"):
    from dragontools.worker.dv_processing_pipeline import DVProcessingPipeline
    from dragontools.worker.dv_runtime_models import DVTempState

    logs = []
    pipeline = DVProcessingPipeline(
        tools=SimpleNamespace(
            ffmpeg="ffmpeg",
            ffprobe="ffprobe",
            mp4box="MP4Box",
            dovi_tool="dovi_tool",
            hdr10plus_tool="hdr10plus_tool",
        ),
        encoder_config=DVEncoderConfig(
            codec=codec,
            crf=21,
            preset="medium",
            options={"encoder": "cpu"},
        ),
        progress_runner=SimpleNamespace(),
        subtitle_rules={},
        temp_state=DVTempState(),
        log=lambda message, level="info": logs.append((level, message)),
    )
    return pipeline, logs


def test_pipeline_p5_string_prueft_libplacebo_vor_jeder_dateiarbeit(tmp_path):
    pipeline, logs = _make_pipeline_for_preflight(codec="h265")
    pipeline._libplacebo_available = lambda: False
    pipeline._build_stages = lambda: (_ for _ in ()).throw(AssertionError("Stages dürfen nicht starten"))
    mi = SimpleNamespace(
        dv_profile_major="5",
        dv_profile="5",
        has_dv=True,
        has_hdrplus=False,
    )

    assert pipeline.run(
        str(tmp_path / "in.mkv"),
        str(tmp_path / "out.mp4"),
        mi,
        [], [], None, [], None,
    ) is False
    assert any("libplacebo" in message for _, message in logs)
    assert not (tmp_path / "out.mp4").exists()


def test_pipeline_lehnt_nicht_h265_dv_fail_fast_ab(tmp_path):
    pipeline, logs = _make_pipeline_for_preflight(codec="h264")
    pipeline._build_stages = lambda: (_ for _ in ()).throw(AssertionError("Stages dürfen nicht starten"))
    mi = SimpleNamespace(dv_profile_major=7, dv_profile="7", has_dv=True, has_hdrplus=False)

    assert pipeline.run(
        str(tmp_path / "in.mkv"),
        str(tmp_path / "out.mp4"),
        mi,
        [], [], None, [], None,
    ) is False
    assert any("nur für HEVC/H.265" in message for _, message in logs)
