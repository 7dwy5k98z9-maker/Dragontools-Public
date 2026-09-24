from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dragontools.worker.converter_strip_subtitles import _mkv_subtitle_args
from dragontools.worker.media_contract_builder import _build_subtitle_tracks
from dragontools.worker.subtitle_sidecar_service import SubtitleSidecarService


def _stream(index: int, codec: str, language: str = "eng", forced: bool = False):
    return SimpleNamespace(index=index, codec=codec, language=language, forced=forced, title="")


def test_strip_mkv_transcodes_mov_text_to_internal_srt_and_copies_other_subtitles():
    mov = _stream(5, "mov_text", forced=True)
    ass = _stream(6, "ass", language="deu")
    plan = SimpleNamespace(burn_sub=None, keep_streams=(mov, ass))

    args = _mkv_subtitle_args(plan)

    pos_mov = args.index("0:5")
    assert args[pos_mov + 1:pos_mov + 3] == ["-c:s:0", "srt"]
    pos_ass = args.index("0:6")
    assert args[pos_ass + 1:pos_ass + 3] == ["-c:s:1", "copy"]


def test_strip_mkv_can_exclude_failed_mov_text_for_backup_retry():
    mov = _stream(5, "mov_text", forced=True)
    ass = _stream(6, "ass", language="deu")
    plan = SimpleNamespace(burn_sub=None, keep_streams=(mov, ass))

    args = _mkv_subtitle_args(plan, exclude_stream_indices={5})

    assert "0:5" not in args
    assert "0:6" in args
    assert "srt" not in args


def test_mov_text_backup_is_lossless_subtitle_only_mp4(monkeypatch, tmp_path):
    stream = _stream(5, "mov_text", language="eng", forced=True)
    captured = {}

    def fake_run_tool(cmd, **kwargs):
        captured["cmd"] = list(cmd)
        Path(cmd[-1]).write_bytes(b"mp4-backup")
        return SimpleNamespace(returncode=0, stdout="", stderr="", aborted=False, timed_out=False)

    monkeypatch.setattr("dragontools.worker.subtitle_movtext_backup.run_tool", fake_run_tool)
    service = SubtitleSidecarService(
        ffmpeg_path="ffmpeg",
        subtitle_rules={},
        log=lambda *_args, **_kwargs: None,
    )
    result = service.export_mov_text_backup_result(
        input_path="source.mp4",
        output_base=tmp_path / "Episode",
        streams=[stream],
    )

    assert result.complete is True
    assert len(result.exported_paths) == 1
    assert result.exported_paths[0].endswith("Episode.en.forced.mov_text.mp4")
    cmd = captured["cmd"]
    assert cmd[cmd.index("-map") + 1] == "0:5"
    assert cmd[cmd.index("-c:s") + 1] == "copy"


def test_media_contract_expects_subrip_for_mov_text_inside_mkv():
    mov = _stream(5, "mov_text", forced=True)
    media_info = SimpleNamespace(subtitle_streams=[mov], audio_streams=[], duration_s=100.0)
    plan = SimpleNamespace(burn_sub=None, keep_streams=(mov,))

    tracks = _build_subtitle_tracks(
        media_info,
        {},
        "mkv",
        False,
        {},
        subtitle_planner=lambda *_args, **_kwargs: plan,
        mp4_storage_planner=lambda *_args, **_kwargs: SimpleNamespace(internal_streams=(mov,)),
        subtitle_codec_family=lambda codec: codec,
    )

    assert len(tracks) == 1
    assert tracks[0].codec == "subrip"
    assert tracks[0].forced is True


def test_media_contract_drops_mov_text_when_externalized_as_backup_sidecar():
    mov = _stream(5, "mov_text", forced=True)
    ass = _stream(6, "ass", language="deu")
    media_info = SimpleNamespace(subtitle_streams=[mov, ass], audio_streams=[], duration_s=100.0)
    plan = SimpleNamespace(burn_sub=None, keep_streams=(mov, ass))

    tracks = _build_subtitle_tracks(
        media_info,
        {},
        "mkv",
        False,
        {},
        subtitle_planner=lambda *_args, **_kwargs: plan,
        mp4_storage_planner=lambda *_args, **_kwargs: SimpleNamespace(internal_streams=(mov, ass)),
        subtitle_codec_family=lambda codec: codec,
        externalized_subtitle_stream_indices=(5,),
    )

    assert len(tracks) == 1
    assert tracks[0].codec == "ass"
    assert tracks[0].language == "de"
