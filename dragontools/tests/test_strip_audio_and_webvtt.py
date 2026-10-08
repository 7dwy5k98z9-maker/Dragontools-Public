"""WebVTT association and verified strip-only audio metadata regressions."""
from copy import deepcopy
import hashlib
from types import SimpleNamespace as NS

import pytest

from dragontools.core.media_analyzer_subtitle_streams import _build_subtitle_streams
from dragontools.core.media_track_pairing import pair_media_tracks


def test_nine_subtitles_keep_global_indices_with_mediainfo_webvtt_name():
    tracks = [{"ID": str(index + 1), "StreamOrder": str(index),
               "Format": "D_WEBVTT/SUBTITLES" if index == 7 else "Advanced SubStation Alpha",
               "Title": "Thai captions" if index == 7 else "Deutsch GPT" if index == 10 else "Original"}
              for index in range(2, 11)]
    probe = [{"index": index, "codec_name": "webvtt" if index == 7 else "ass",
              "tags": {"language": "tha" if index == 7 else "ger"}}
             for index in range(2, 11)]
    warnings = []
    result = _build_subtitle_streams(tracks, probe, warnings)
    assert [stream.index for stream in result] == list(range(2, 11))
    assert result[5].codec == "webvtt"
    assert result[5].title == "Thai captions"
    assert result[-1].codec == "ass"
    assert result[-1].title == "Deutsch GPT"
    assert not warnings


def test_webvtt_container_identity_wins_over_order_and_global_index():
    tracks = [{"ID": "20", "Format": "D_WEBVTT/SUBTITLES", "Title": "Second"},
              {"ID": "10", "Format": "D_WEBVTT/SUBTITLES", "Title": "First"}]
    probe = [{"index": 7, "id": "0xa", "codec_name": "webvtt"},
             {"index": 10, "id": "0x14", "codec_name": "webvtt"}]
    warnings = []
    pairs = pair_media_tracks(tracks, probe, warnings)
    assert [(track["Title"], stream["index"]) for track, stream in pairs] == [("First", 7), ("Second", 10)]
    assert not warnings


def test_webvtt_alias_does_not_hide_conflicting_identity():
    warnings = []
    pairs = pair_media_tracks(
        [{"ID": "20", "Format": "D_WEBVTT/SUBTITLES", "Title": "Foreign"}],
        [{"index": 7, "id": "0xa", "codec_name": "webvtt"}], warnings)
    assert pairs[0][0] == {}
    assert len(warnings) == 1


def test_mediainfo_only_webvtt_is_not_mistaken_for_subt():
    result = _build_subtitle_streams([{"Format": "D_WEBVTT/SUBTITLES"}], [])
    assert result[0].codec == "webvtt"


@pytest.mark.media_integration
@pytest.mark.parametrize("audio_codec,source_bitrate,expected_title", [
    ("copy", 160000, "Chinesisch AAC Stereo 160kbps"),
    ("copy", None, "Chinesisch"),
    ("aac", 160000, "Chinesisch AAC Stereo 192kbps"),
])
def test_real_strip_only_output_passes_audio_metadata_contract(
        tmp_path, monkeypatch, audio_codec, source_bitrate, expected_title):
    from dragontools.core.media_analyzer import analyze_media
    from dragontools.rules import audio_plan
    from dragontools.rules.audio_rule_basics import _DEFAULT_RULES
    from dragontools.tests.ci_requirements import external_media_environment, _resolve_tool
    from dragontools.tests.test_patch12_real_media import run, probe
    from dragontools.worker.converter_strip import ConverterStripHelper
    from dragontools.worker.media_contract import build_expected_media_contract
    from dragontools.worker.output_verifier import OutputVerifier

    environment = external_media_environment()
    if not environment.ffmpeg or not environment.ffprobe:
        pytest.skip("FFmpeg/ffprobe unavailable")
    tools = NS(ffmpeg=environment.ffmpeg, ffprobe=environment.ffprobe,
               mediainfo=_resolve_tool("DRAGONTOOLS_MEDIAINFO", "MediaInfo.exe", "mediainfo"))
    rules = deepcopy(_DEFAULT_RULES)
    rules["extra_stereo"] = False
    monkeypatch.setattr(audio_plan, "_load_audio_rules", lambda: rules)
    source = tmp_path / "untitled-chinese.mkv"
    source_tags = ["-metadata:s:a:0", f"BPS={source_bitrate}"] if source_bitrate else []
    run([tools.ffmpeg, "-y", "-v", "error", "-f", "lavfi", "-i",
         "testsrc2=size=160x90:rate=25:duration=3", "-f", "lavfi", "-i",
         "sine=frequency=440:sample_rate=48000:duration=3", "-map", "0:v", "-map", "1:a",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-ac", "2", "-b:a", "160k",
         "-metadata:s:a:0", "language=chi", "-disposition:a:0", "default+forced", *source_tags, str(source)])
    digest = hashlib.sha256(source.read_bytes()).hexdigest()
    before = probe(source, tools)
    original_audio = next(stream for stream in before["streams"] if stream["codec_type"] == "audio")
    assert not original_audio.get("tags", {}).get("title")
    info = analyze_media(str(source), tools)
    override = {"audio_mode": "custom", "audio_tracks": [
        {"index": info.audio_streams[0].index, "mode": "custom", "codec": audio_codec, "bitrate": 192000}],
        "audio_drc": {"mode": "off"}, "audio_loudnorm": {"mode": "off"}}
    subtitle_rules = {"additional_sidecars_enabled": False, "text_to_srt_sidecar_enabled": False,
                      "pgs_to_srt_enabled": False, "pgs_original_storage": "internal_mkv"}
    commands = []
    def execute(command):
        commands.append(command)
        return run(command).returncode
    worker = NS(tools=tools, subtitle_rules=subtitle_rules, log=lambda *_: None,
                _progress=NS(run=execute))
    output = tmp_path / "stripped.mkv"
    assert ConverterStripHelper(worker).strip_only(str(source), str(output), info, override, "mkv")
    contract = build_expected_media_contract(
        media_info=info, file_override=override, container="mkv", pipeline="standard", strip_only=True,
        effective_codec="h265", effective_preserve_hdrplus=False, subtitle_rules=subtitle_rules)
    result = OutputVerifier(ffprobe_path=tools.ffprobe).verify(
        str(output), "mkv", expected_duration_ms=round(info.duration_s * 1000),
        source_has_audio=True, expected_contract=contract)
    assert result.ok, result.messages
    after = probe(output, tools)
    audio = next(stream for stream in after["streams"] if stream["codec_type"] == "audio")
    assert audio["tags"]["title"] == expected_title
    assert audio["disposition"]["default"] == 1
    assert audio["disposition"]["forced"] == 1
    command = commands[0]
    assert command[command.index("-c:a:0") + 1] == audio_codec
    assert command[command.index("-c:v") + 1] == "copy"
    assert hashlib.sha256(source.read_bytes()).hexdigest() == digest
