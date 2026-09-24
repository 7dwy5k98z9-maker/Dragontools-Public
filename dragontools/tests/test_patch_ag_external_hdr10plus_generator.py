from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.hdr10plus_generation import (
    decide_hdr10plus_generation,
    source_is_hdr10_pq_compatible,
)
from dragontools.core.models import MediaInfo, Pipeline, VideoStream
from dragontools.core.sdr_hdr_enhancement import decide_sdr_hdr_enhancement
from dragontools.rules.pipeline_selector import resolve_pipeline_context
from dragontools.worker.dv_dynamic_metadata_service import DVDynamicMetadataService
from dragontools.worker.dv_pipeline_context import DVPipelineState, DVRunRequest, DVWorkFiles
from dragontools.worker.hdr10plus_generator_client import (
    HDR10PlusGeneratorClient,
    HDR10PlusGeneratorResult,
)
from dragontools.worker.hdrplus_pipeline_coordinator import (
    HDRPlusPipelineCoordinator,
    HDRPlusPipelineHooks,
)
from dragontools.worker.hdrplus_runtime_models import HDRPlusEncoderConfig, HDRPlusExecutionContext
from dragontools.worker.media_contract import build_expected_media_contract
from dragontools.worker.tool_runner import ToolRunResult


def _media(
    *,
    transfer: str = "smpte2084",
    primaries: str = "bt2020",
    hdr10plus: bool = False,
    dv: bool = False,
    dv_profile: int | None = None,
    codec: str = "hevc",
) -> MediaInfo:
    stream = VideoStream(
        index=0,
        codec=codec,
        width=3840,
        height=2160,
        hdr_format="hdr10plus" if hdr10plus else "dolby_vision" if dv else "hdr10",
        has_hdr10plus=hdr10plus,
        has_dolby_vision=dv,
        bit_depth=10,
        color_space="bt709" if primaries.lower() in {"bt709", "bt.709"} else "bt2020nc",
        color_transfer=transfer,
        color_primaries=primaries,
    )
    return MediaInfo(
        path="source.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[stream],
        is_hdr=transfer.lower() not in {"bt709", "iec61966-2-1"},
        has_hdr10plus=hdr10plus,
        dolby_vision=dv,
        dv_profile=str(dv_profile) if dv_profile is not None else None,
        dv_profile_major=dv_profile,
        transfer_characteristics=transfer,
    )


def test_generation_policy_is_disabled_and_tool_fail_closed():
    media = _media()
    disabled = decide_hdr10plus_generation(media, target_codec="h265", enabled=False, tool_available=True)
    missing = decide_hdr10plus_generation(media, target_codec="h265", enabled=True, tool_available=False)
    assert disabled.eligible is False and disabled.code == "DISABLED"
    assert missing.eligible is False and missing.code == "TOOL_UNAVAILABLE"


@pytest.mark.parametrize(
    ("transfer", "expected_code"),
    [("bt709", "SOURCE_NOT_PQ"), ("arib-std-b67", "SOURCE_HLG")],
)
def test_sdr_and_hlg_are_not_sent_to_generator(transfer, expected_code):
    media = _media(transfer=transfer, primaries="bt709" if transfer == "bt709" else "bt2020")
    decision = decide_hdr10plus_generation(media, target_codec="h265", enabled=True, tool_available=True)
    assert decision.eligible is False
    assert decision.code == expected_code


def test_pq_without_hdr10plus_is_accepted_but_existing_hdr10plus_is_not_regenerated():
    pq = decide_hdr10plus_generation(_media(), target_codec="h265", enabled=True, tool_available=True)
    existing = decide_hdr10plus_generation(
        _media(hdr10plus=True), target_codec="h265", enabled=True, tool_available=True
    )
    assert pq.eligible is True and pq.code == "ELIGIBLE"
    assert existing.eligible is False and existing.code == "HDR10PLUS_PRESENT"


def test_pq_classifier_does_not_use_generic_is_hdr_flag():
    hlg = _media(transfer="arib-std-b67")
    hlg.is_hdr = True
    ok, reason = source_is_hdr10_pq_compatible(hlg)
    assert ok is False
    assert "HLG" in reason


def test_dv81_pq_selects_dv_pipeline_and_generation_without_dropping_dv():
    media = _media(dv=True, dv_profile=8)
    selection = resolve_pipeline_context(
        media,
        codec="h265",
        hdr10plus_generator_enabled=True,
        hdr10plus_generator_available=True,
    )
    assert selection["pipeline"] == Pipeline.DV
    assert selection["generate_hdr10plus"] is True
    assert selection["effective_preserve_dv"] is True

    request = DVRunRequest.create(
        input_path="in.mkv",
        output_path="out.mp4",
        media_info=media,
        vf_args=[],
        audio_args=[],
        audio_input_args=[],
        sn=["-sn"],
        crop=None,
        override={},
        preserve_hdrplus=True,
        generate_hdr10plus=True,
    )
    assert request.preserve_dv_hdr10plus_combo is False
    assert request.requires_hdr10plus is True
    assert request.profile_major == 8


def test_non_profile8_dv_is_not_auto_generated():
    decision = decide_hdr10plus_generation(
        _media(dv=True, dv_profile=7),
        target_codec="h265",
        enabled=True,
        tool_available=True,
    )
    assert decision.eligible is False
    assert decision.code == "DV_PROFILE_NOT_8"


def test_pipeline_selection_existing_hdr10plus_remains_preserve_mode():
    selection = resolve_pipeline_context(
        _media(hdr10plus=True),
        codec="h265",
        hdr10plus_generator_enabled=True,
        hdr10plus_generator_available=True,
    )
    assert selection["pipeline"] == Pipeline.HDRPLUS
    assert selection["generate_hdr10plus"] is False
    assert selection["effective_preserve_hdrplus"] is True


def _fake_executable(tmp_path: Path) -> Path:
    exe = tmp_path / "Werkzeuge mit Umlaut ä" / "HDR Plus Generator.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("placeholder", encoding="utf-8")
    return exe


def test_generator_version_contract_and_exact_cli_command_with_unicode_paths(tmp_path):
    exe = _fake_executable(tmp_path)
    calls: list[list[str]] = []

    def fake_run(command, **_kwargs):
        calls.append(list(command))
        return ToolRunResult(
            command=list(command),
            returncode=0,
            stdout=json.dumps({"success": True, "version": "1.2.3"}),
        )

    client = HDR10PlusGeneratorClient(str(exe), run_tool_fn=fake_run)
    version = client.probe_version()
    assert version.success is True
    assert version.version == "1.2.3"
    assert calls == [[str(exe), "--version"]]

    source = tmp_path / "Filme mit Leerzeichen" / "Überraschung – HDR.mkv"
    source.parent.mkdir()
    source.write_bytes(b"video")
    output = tmp_path / "Ziel ä" / "hdr10plus.json"
    output.parent.mkdir()

    def fake_analyze(command, **_kwargs):
        calls.append(list(command))
        Path(command[command.index("--output") + 1]).write_text('{"SceneInfo":[]}', encoding="utf-8")
        return ToolRunResult(
            command=list(command), returncode=0,
            stdout=json.dumps({
                "success": True, "version": "1.2.3", "input": str(source),
                "output": str(output), "frames": 143812, "scenes": 1247,
                "transfer": "smpte2084",
            }),
        )

    client = HDR10PlusGeneratorClient(str(exe), run_tool_fn=fake_analyze)
    result = client.analyze(source, output)
    assert result.success is True
    assert result.frames == 143812 and result.scenes == 1247
    assert calls[-1] == [str(exe), "analyze", "--input", str(source), "--output", str(output)]


def test_generator_structured_failure_exitcode_invalid_json_and_abort(tmp_path):
    exe = _fake_executable(tmp_path)

    client = HDR10PlusGeneratorClient(
        str(exe),
        run_tool_fn=lambda command, **kwargs: ToolRunResult(
            command=list(command), returncode=3,
            stdout=json.dumps({"success": False, "error": "SOURCE_NOT_PQ", "message": "not PQ"}),
        ),
    )
    failure = client.probe_version()
    assert failure.success is False
    assert failure.returncode == 3
    assert failure.error == "SOURCE_NOT_PQ"

    invalid = HDR10PlusGeneratorClient(
        str(exe),
        run_tool_fn=lambda command, **kwargs: ToolRunResult(command=list(command), returncode=0, stdout="human log text"),
    ).probe_version()
    assert invalid.success is False
    assert invalid.error == "INVALID_JSON_RESPONSE"

    aborted = HDR10PlusGeneratorClient(
        str(exe),
        run_tool_fn=lambda command, **kwargs: ToolRunResult(command=list(command), returncode=130, aborted=True),
    ).probe_version()
    assert aborted.success is False and aborted.aborted is True and aborted.error == "ABORTED"


def test_generator_missing_path_and_failed_analyze_remove_stale_output(tmp_path):
    missing = HDR10PlusGeneratorClient(str(tmp_path / "missing.exe")).probe_version()
    assert missing.success is False and missing.returncode == 127

    exe = _fake_executable(tmp_path)
    output = tmp_path / "hdr10plus.json"
    output.write_text("stale", encoding="utf-8")
    client = HDR10PlusGeneratorClient(
        str(exe),
        run_tool_fn=lambda command, **kwargs: ToolRunResult(
            command=list(command), returncode=2,
            stdout=json.dumps({"success": False, "error": "ANALYSIS_FAILED", "message": "bad frame"}),
        ),
    )
    result = client.analyze(tmp_path / "source.mkv", output)
    assert result.success is False
    assert not output.exists()


class _FakeEncode:
    def __init__(self, events):
        self.events = events

    def encode(self, *, encoded_hevc, stream_donor, **_kwargs):
        self.events.append("encode")
        encoded_hevc.write_bytes(b"encoded" * 512)
        return True


class _NoSidecars:
    def export_sidecars_result(self, **_kwargs):
        raise AssertionError("sidecar export is not expected")


class _NoMp4Subtitles:
    def prepare_internal_mp4_tracks(self, **_kwargs):
        raise AssertionError("MP4 subtitle path is not expected")


def test_generated_hdrplus_pipeline_order_and_temp_cleanup(tmp_path):
    events: list[str] = []
    output = tmp_path / "final.mkv"
    captured_temp: list[Path] = []
    coordinator = HDRPlusPipelineCoordinator(
        encode_service=_FakeEncode(events),
        subtitle_service=_NoSidecars(),
        subtitle_mux_service=_NoMp4Subtitles(),
        subtitle_rules={},
        log=lambda *_: None,
    )
    context = HDRPlusExecutionContext.create(
        input_path=str(tmp_path / "source.mkv"),
        output_path=str(output),
        media_info=_media(codec="h264"),
        vf_args=["-vf", "scale=1920:1080"],
        audio_args=["-an"],
        audio_input_args=[],
        subtitle_args=["-sn"],
        crop="crop=1920:800:0:140",
        container="mkv",
        override={},
        encoder=HDRPlusEncoderConfig.create(codec="h265", crf=22, preset="medium", encoder_options={}),
        generate_hdr10plus=True,
    )

    def generate(final_hevc, metadata_json):
        events.append("generate")
        assert Path(final_hevc).is_file()
        captured_temp.append(Path(metadata_json).parent)
        Path(metadata_json).write_text('{"SceneInfo":[]}', encoding="utf-8")
        return True

    def inject(encoded, metadata, injected):
        events.append("inject")
        assert Path(encoded).is_file() and Path(metadata).is_file()
        Path(injected).write_bytes(b"injected" * 512)
        return True

    def mux(injected, _donor, target, **_kwargs):
        events.append("mux")
        Path(target).write_bytes(Path(injected).read_bytes())
        return True

    def verify(_target, metadata):
        events.append("verify")
        assert Path(metadata).is_file()
        return True

    hooks = HDRPlusPipelineHooks(
        extract_hevc_annexb=lambda *_: (_ for _ in ()).throw(AssertionError("no source extraction in generate mode")),
        extract_metadata=lambda *_: (_ for _ in ()).throw(AssertionError("no source metadata extraction in generate mode")),
        generate_metadata=generate,
        inject_metadata=inject,
        mux_output=mux,
        run_mux_tool=lambda *_args, **_kwargs: True,
        verify_final=verify,
        cleanup_tmp_sub=lambda *_: None,
    )
    outcome = coordinator.run(context, hooks)
    assert outcome.success is True and outcome.verified_hdr10plus is True
    assert events == ["encode", "generate", "inject", "mux", "verify"]
    # No pixel-changing operation exists after generation; the remaining stages are metadata/mux/verify only.
    assert events[events.index("generate") + 1 :] == ["inject", "mux", "verify"]
    assert captured_temp and not captured_temp[0].exists()


def test_dv_generated_metadata_is_injected_before_dv_rpu(tmp_path):
    events: list[str] = []
    media = _media(dv=True, dv_profile=8)
    request = DVRunRequest.create(
        input_path=str(tmp_path / "in.mkv"), output_path=str(tmp_path / "out.mp4"),
        media_info=media, vf_args=[], audio_args=[], audio_input_args=[], sn=["-sn"],
        crop=None, override={}, preserve_hdrplus=False, generate_hdr10plus=True,
    )
    files = DVWorkFiles.create(tmp_path)
    files.enc_hevc.write_bytes(b"encoded" * 512)
    files.rpu_final.write_bytes(b"rpu")
    state = DVPipelineState(request=request, files=files, rpu_to_use=files.rpu_final)

    class Generator:
        def analyze(self, encoded, output):
            events.append("generate")
            assert Path(encoded) == files.enc_hevc
            Path(output).write_text('{"SceneInfo":[]}', encoding="utf-8")
            return HDR10PlusGeneratorResult(True, 0)

    class Hdr:
        def inject_metadata(self, _run, *, input_hevc, metadata_json, output_hevc):
            events.append("hdr10plus-inject")
            assert Path(input_hevc) == files.enc_hevc
            Path(output_hevc).write_bytes(b"hdr" * 512)
            return True

        def verify_metadata(self, _run, **_kwargs):
            events.append("hdr10plus-verify")
            return True

    class Rpu:
        def inject_rpu(self, _run, *, input_hevc, input_rpu, output_hevc):
            events.append("dv-rpu-inject")
            assert Path(input_hevc) == files.hdr10plus_hevc
            assert Path(input_rpu) == files.rpu_final
            Path(output_hevc).write_bytes(b"dv" * 512)
            return True

    runner = SimpleNamespace(adapter=lambda **_kwargs: (lambda *_args, **_kw: 0))
    service = DVDynamicMetadataService(
        tools=SimpleNamespace(), temp_state=SimpleNamespace(record_failure=lambda **_kwargs: None),
        audio_mux_service=None, rpu_service=Rpu(), hdr10plus_service=Hdr(), generator_client=Generator(),
        level5_editor=None, failure_recovery=None, log=lambda *_: None, verbose_log=lambda *_: None,
        assert_nonempty_file=lambda path, _label: Path(path).is_file() and Path(path).stat().st_size > 0,
    )
    ok = service.inject_dynamic_metadata(
        state, runner,
        validate_rpu_frame_parity=lambda *_args, **_kwargs: events.append("parity") or True,
        verify_injected_rpu=lambda *_args, **_kwargs: events.append("dv-verify") or True,
    )
    assert ok is True
    assert events == [
        "generate", "hdr10plus-inject", "parity", "dv-rpu-inject", "dv-verify", "hdr10plus-verify"
    ]


def test_generated_dv_media_contract_requires_both_dynamic_metadata():
    contract = build_expected_media_contract(
        media_info=_media(dv=True, dv_profile=8),
        file_override={}, container="mp4", pipeline="dv", strip_only=False,
        effective_codec="h265", effective_preserve_hdrplus=False,
        generate_hdr10plus=True, subtitle_rules={}, effective_scale_mode="none", crop_filter=None,
    )
    assert contract.require_dolby_vision is True
    assert contract.require_hdr10plus is True


def test_davinci_free_backend_is_prepared_only_and_ffmpeg_backend_is_unchanged():
    media = _media(transfer="bt709", primaries="bt709")
    media.is_hdr = False

    ffmpeg = decide_sdr_hdr_enhancement(
        media,
        target_codec="h265",
        encoder_options={
            "sdr_hdr_enabled": True,
            "sdr_hdr_backend": "ffmpeg",
            "_sdr_hdr_libplacebo_available": True,
        },
    )
    assert ffmpeg.applied is True
    assert ffmpeg.filter_chain

    davinci_missing = decide_sdr_hdr_enhancement(
        media,
        target_codec="h265",
        encoder_options={
            "sdr_hdr_enabled": True,
            "sdr_hdr_backend": "davinci_free",
            "_davinci_resolve_available": False,
            "_sdr_hdr_libplacebo_available": True,
        },
    )
    assert davinci_missing.applied is False and davinci_missing.filter_chain == ()
    assert "nicht verfügbar" in davinci_missing.reason

    davinci_present = decide_sdr_hdr_enhancement(
        media,
        target_codec="h265",
        encoder_options={
            "sdr_hdr_enabled": True,
            "sdr_hdr_backend": "davinci_free",
            "_davinci_resolve_available": True,
            "_sdr_hdr_libplacebo_available": True,
        },
    )
    assert davinci_present.applied is False and davinci_present.filter_chain == ()
    assert "vorbereitet" in davinci_present.reason

    # Selecting/detecting Resolve is isolated from the default FFmpeg decision.
    ffmpeg_with_resolve_installed = decide_sdr_hdr_enhancement(
        media,
        target_codec="h265",
        encoder_options={
            "sdr_hdr_enabled": True,
            "sdr_hdr_backend": "ffmpeg",
            "_davinci_resolve_available": True,
            "_sdr_hdr_libplacebo_available": True,
        },
    )
    assert ffmpeg_with_resolve_installed == ffmpeg


def test_tool_paths_resolve_custom_generator_and_standard_davinci_install(monkeypatch, tmp_path: Path):
    import dragontools.core.tool_paths as tool_paths_module

    generator_dir = tmp_path / "Werkzeuge mit Umlaut ä"
    generator_dir.mkdir()
    generator = generator_dir / "HDRPlusGenerator.exe"
    generator.write_bytes(b"exe")

    program_files = tmp_path / "Program Files"
    resolve = program_files / "Blackmagic Design" / "DaVinci Resolve" / "Resolve.exe"
    resolve.parent.mkdir(parents=True)
    resolve.write_bytes(b"exe")

    class Provider:
        def get_custom_dirs(self):
            return []

        def find_in_settings(self, tool_key: str, *exe_names: str):
            if tool_key == "hdr10plus_generator":
                return str(generator_dir)
            return None

    monkeypatch.setattr(tool_paths_module.shutil, "which", lambda _name: None)
    monkeypatch.setenv("ProgramFiles", str(program_files))
    monkeypatch.delenv("ProgramW6432", raising=False)

    tools = tool_paths_module.ToolPaths(provider=Provider())
    assert Path(tools.hdr10plus_generator) == generator
    assert Path(tools.davinci_resolve) == resolve


def test_source_packager_keeps_standalone_generator_project_separate_from_pyinstaller():
    root = Path(__file__).resolve().parents[2]
    source_zip = (root / "DragonTools_Source_ZIP.bat").read_text(encoding="utf-8")
    build = (root / "build_v9.bat").read_text(encoding="utf-8")
    assert 'CopyRequiredDir "dragon_hdr10plus_generator"' in source_zip
    assert "dragon_hdr10plus_generator" not in build


def test_explicit_standard_pipeline_suppresses_generation_contract():
    selection = resolve_pipeline_context(
        _media(),
        codec="h265",
        job_pipeline="standard",
        hdr10plus_generator_enabled=True,
        hdr10plus_generator_available=True,
    )
    assert selection["pipeline"] == Pipeline.STANDARD
    assert selection["generate_hdr10plus"] is False
    assert selection["hdr10plus_generation_code"] == "PIPELINE_OVERRIDE"


def test_dv_source_cannot_force_generated_hdr10plus_through_non_dv_hdrplus_pipeline():
    from dragontools.rules.pipeline_selector import PipelineCapabilityError

    with pytest.raises(PipelineCapabilityError, match="Dolby-Vision-Pipeline"):
        resolve_pipeline_context(
            _media(dv=True, dv_profile=8),
            codec="h265",
            job_pipeline="hdrplus",
            hdr10plus_generator_enabled=True,
            hdr10plus_generator_available=True,
        )
