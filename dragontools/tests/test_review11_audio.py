# -*- coding: utf-8 -*-
"""Regression tests for Review 11: audio selection/transcode/mux/sync/language."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.audio_sync_planner import AudioSyncPlanner
from dragontools.core.audio_video_match_models import AudioSyncPlan, TimeMappingResult, VideoInfo
from dragontools.core.models import AudioStream
from dragontools.rules.audio_plan import compute_audio_track_plan, output_default_for_decision
from dragontools.rules.audio_rule_basics import _DEFAULT_RULES
from dragontools.rules.audio_selection import choose_audio_streams
from dragontools.worker.audio_video_match_render import build_mux_command
from dragontools.worker.converter_audio_args import build_audio_args
from dragontools.worker.converter_strip_audio import build_strip_audio_args


def _audio(
    index: int,
    *,
    language: str | None = "de",
    codec: str = "aac",
    channels: int = 2,
    bitrate: int | None = 256_000,
    title: str | None = None,
    default: bool = False,
) -> AudioStream:
    return AudioStream(
        index=index,
        language=language,
        forced=False,
        title=title,
        codec=codec,
        channels=channels,
        bitrate=bitrate,
        default=default,
    )


def _rules() -> dict:
    return deepcopy(_DEFAULT_RULES)


def _mapping(streams: list[AudioStream]) -> TimeMappingResult:
    source = VideoInfo(path="source.mkv", duration_s=60.0, audio_streams=streams)
    target = VideoInfo(path="target.mkv", duration_s=60.0)
    return TimeMappingResult(
        mode="A",
        offset_s=0.0,
        speed_factor=1.0,
        residual_error_s=0.0,
        drift_s=0.0,
        confidence_percent=100.0,
        match_points=[],
        unmatched_reference_times=[],
        source_info=source,
        target_info=target,
        common_end_target_s=60.0,
        can_process=True,
    )


def test_commentary_and_descriptive_hard_exclusions_are_not_reintroduced_by_fallback():
    rules = _rules()
    rules.update(
        {
            "ignore_commentary_tracks": True,
            "ignore_descriptive_audio": True,
            "fallback_if_no_priority_match": "keep_all",
        }
    )
    streams = [
        _audio(1, title="Director Commentary"),
        _audio(2, title="Audiodeskription"),
    ]

    assert choose_audio_streams(streams, rules) == []


@pytest.mark.parametrize(
    ("channels", "source_codec", "source_bitrate", "expected_codec", "expected_bitrate"),
    [
        (1, "mp3", 192_000, "aac", 128_000),
        (2, "mp3", 320_000, "aac", 256_000),
        (6, "dts", 1_500_000, "eac3", 640_000),
    ],
)
def test_default_channel_policy_matches_audio_contract(
    channels, source_codec, source_bitrate, expected_codec, expected_bitrate
):
    plan = compute_audio_track_plan(
        [_audio(1, codec=source_codec, channels=channels, bitrate=source_bitrate)],
        None,
        "mkv",
        rules=_rules(),
    )

    assert len(plan) == 1
    assert plan[0].needs_transcode is True
    assert plan[0].target_codec == expected_codec
    assert plan[0].target_bitrate == expected_bitrate


def test_custom_codec_without_bitrate_uses_channel_policy_when_source_bitrate_unknown():
    stream = _audio(3, codec="pcm_s16le", channels=1, bitrate=None, title="Deutsch")
    override = {
        "audio_mode": "custom",
        "audio_tracks": [
            {
                "index": 3,
                "mode": "custom",
                "codec": "aac",
                "bitrate": None,
                "source_identity": {
                    "language": "de",
                    "codec": "pcm_s16le",
                    "channels": 1,
                    "title": "Deutsch",
                },
            }
        ],
    }

    plan = compute_audio_track_plan([stream], override, "mkv", rules=_rules())

    assert len(plan) == 1
    assert plan[0].target_codec == "aac"
    assert plan[0].target_channels == 1
    assert plan[0].target_bitrate == 128_000


def test_custom_track_override_remaps_by_source_identity_after_stream_reorder():
    streams = [
        _audio(1, language="en", title="English"),
        _audio(2, language="de", title="Deutsch"),
    ]
    override = {
        "audio_mode": "custom",
        "audio_tracks": [
            {
                "index": 1,  # index from the old probe; now occupied by English
                "mode": "custom",
                "codec": "eac3",
                "bitrate": 640_000,
                "source_identity": {
                    "language": "de",
                    "codec": "aac",
                    "channels": 2,
                    "title": "Deutsch",
                },
            }
        ],
    }

    plan = compute_audio_track_plan(streams, override, "mkv", rules=_rules())

    assert [decision.stream.index for decision in plan] == [2]
    assert plan[0].stream.language == "de"
    assert plan[0].target_codec == "eac3"


def test_ambiguous_stale_custom_track_identity_fails_closed_instead_of_auto_selecting():
    streams = [
        _audio(1, language="de", title="Deutsch"),
        _audio(2, language="de", title="Deutsch"),
    ]
    override = {
        "audio_mode": "custom",
        "audio_tracks": [
            {
                "index": 99,
                "mode": "custom",
                "codec": "aac",
                "bitrate": 256_000,
                "source_identity": {
                    "language": "de",
                    "codec": "aac",
                    "channels": 2,
                    "title": "Deutsch",
                },
            }
        ],
    }

    assert compute_audio_track_plan(streams, override, "mkv", rules=_rules()) == []


def test_generated_extra_stereo_never_inherits_source_default_disposition():
    rules = _rules()
    rules["extra_stereo"] = True
    stream = _audio(1, codec="eac3", channels=6, bitrate=640_000, default=True)
    plan = compute_audio_track_plan([stream], None, "mkv", rules=rules)

    assert len(plan) == 2
    assert output_default_for_decision(plan[0]) is True
    assert plan[1].is_extra_stereo is True
    assert output_default_for_decision(plan[1]) is False

    class _Logger:
        def decision(self, *_args, **_kwargs):
            pass

        def audio(self, *_args, **_kwargs):
            pass

    args = build_audio_args(
        SimpleNamespace(_logger=_Logger()),
        SimpleNamespace(audio_streams=[stream]),
        None,
        "mkv",
    )
    # The default rules loaded by build_audio_args may not enable extra-stereo;
    # the explicit helper assertions above prove the duplicate-default fix.
    assert "-disposition:a:0" in args
    assert args[args.index("-disposition:a:0") + 1] == "default"



def test_ffmpeg_audio_language_metadata_uses_iso639_2_tag_for_mp4_and_strip_paths():
    stream = _audio(1, language="de", codec="aac", channels=2, bitrate=256_000)

    class _Logger:
        def decision(self, *_args, **_kwargs):
            pass

        def audio(self, *_args, **_kwargs):
            pass

    mi = SimpleNamespace(audio_streams=[stream])
    normal_args = build_audio_args(SimpleNamespace(_logger=_Logger()), mi, None, "mp4")
    _, strip_args = build_strip_audio_args(mi, None, "mp4")

    assert "language=deu" in normal_args
    assert "language=de" not in normal_args
    assert "language=deu" in strip_args
    assert "language=de" not in strip_args

def test_audio_sync_mono_uses_128k_and_missing_explicit_track_does_not_fallback():
    stream = _audio(4, channels=1, bitrate=96_000)
    planner = AudioSyncPlanner()

    mono_plan = planner.build_plan(_mapping([stream]), audio_stream_index=4)
    stale_plan = planner.build_plan(_mapping([stream]), audio_stream_index=99)

    assert mono_plan.target_codec == "aac"
    assert mono_plan.target_bitrate == "128k"
    assert stale_plan.blocked is True
    assert stale_plan.audio_stream_index == -1
    assert "#99" in stale_plan.block_reason


def test_audio_video_match_mux_uses_selected_language_and_clears_old_defaults(tmp_path: Path):
    plan = AudioSyncPlan(
        mode="A",
        audio_stream_index=2,
        target_duration_s=60.0,
        segments=[],
        filter_kind="af",
        filter_graph="",
        target_codec="aac",
        target_bitrate="256k",
        target_language="en",
    )
    tools = SimpleNamespace(ffmpeg="ffmpeg")
    cmd = build_mux_command(
        tools,
        "target.mkv",
        tmp_path / "audio.mka",
        tmp_path / "output.mkv",
        plan=plan,
    )

    lang_pos = cmd.index("-metadata:s:a:0")
    assert cmd[lang_pos + 1] == "language=eng"
    clear_pos = cmd.index("-disposition:a")
    assert cmd[clear_pos + 1] == "-default"  # Retain forced flags on original tracks.
    default_pos = cmd.index("-disposition:a:0")
    assert cmd[default_pos + 1] == "default"


def test_audio_mux_abort_after_verification_prevents_transactional_commit(monkeypatch, tmp_path: Path):
    from dragontools.worker import audio_mux_job as module

    src = tmp_path / "movie.mkv"
    src.write_bytes(b"SOURCE")
    staging = tmp_path / "movie.__audio_mux_tmp__.mkv"

    media_info = SimpleNamespace(
        video_streams=[SimpleNamespace(codec="hevc")],
        audio_streams=[_audio(1)],
        subtitle_streams=[],
        analysis_source="test",
        duration_s=10.0,
    )
    monkeypatch.setattr(module, "analyze_media", lambda *_args, **_kwargs: media_info)

    committed: list[bool] = []

    def _commit(**_kwargs):
        committed.append(True)

    monkeypatch.setattr(module, "commit_staged_output", _commit)

    class _Signal:
        def __init__(self):
            self.values = []

        def emit(self, *args):
            self.values.append(args)

    worker = SimpleNamespace(
        progress_file=_Signal(),
        log_line=_Signal(),
        file_result=_Signal(),
        tools=SimpleNamespace(),
        overwrite_original=True,
        abort_requested=False,
        abort_type="sofort",
    )

    generated = []

    def _run_ffmpeg(cmd, *_args, **_kwargs):
        owned_staging = Path(cmd[-1])
        owned_staging.write_bytes(b"STAGING")
        generated.append(owned_staging)
        return 0

    worker.run_ffmpeg_with_progress = _run_ffmpeg

    planner = SimpleNamespace(
        build_audio_plan=lambda _mi: [],
        build_expected_contract=lambda *_args: object(),
        build_output_path=lambda *_args: (src, staging),
        build_ffmpeg_cmd=lambda _src, out, _plan: ["ffmpeg", out],
    )

    class _Verifier:
        def verify(self, **_kwargs):
            worker.abort_requested = True
            return SimpleNamespace(ok=True, messages=[])

    module.AudioMuxJobRunner(worker, planner=planner, verifier=_Verifier()).run(str(src))

    assert committed == []
    assert src.read_bytes() == b"SOURCE"
    assert generated and not generated[0].exists()
    assert not staging.exists()
    assert worker.file_result.values[-1][1] is False


def test_audio_video_match_abort_during_validation_never_commits_output(monkeypatch, tmp_path: Path):
    from dragontools.worker import audio_video_match_create_service as module
    from dragontools.worker.audio_video_match_contracts import AudioVideoMatchCallbacks
    from dragontools.worker.audio_video_match_runtime import AudioVideoMatchProgress, AudioVideoMatchToolIO

    aborted = {"value": False}
    temp_output = tmp_path / "staged.mkv"
    final_output = tmp_path / "final.mkv"
    temp_output.write_bytes(b"STAGED")

    def _validate(*_args, **_kwargs):
        aborted["value"] = True
        return 60.0

    monkeypatch.setattr(module, "validate_output", _validate)

    callbacks = AudioVideoMatchCallbacks(
        log_line=lambda _msg: None,
        progress=lambda _value: None,
        analysis_ready=lambda _value: None,
        cuts_ready=lambda _value: None,
        plan_ready=lambda _value: None,
        result_ready=lambda _value: None,
    )
    tool_io = AudioVideoMatchToolIO(
        callbacks=callbacks,
        process_worker=None,
        is_aborted=lambda: aborted["value"],
    )
    service = module.AudioVideoMatchCreateService(
        tools=SimpleNamespace(),
        callbacks=callbacks,
        progress=AudioVideoMatchProgress(callbacks),
        tool_io=tool_io,
    )
    mapping = SimpleNamespace(target_info=SimpleNamespace(duration_s=60.0))

    with pytest.raises(RuntimeError, match="Abgebrochen"):
        service._validate_and_commit(mapping, temp_output, final_output)

    assert temp_output.exists()
    assert not final_output.exists()
