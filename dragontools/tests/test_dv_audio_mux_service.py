from __future__ import annotations

from types import SimpleNamespace

from dragontools.worker.dv_audio_mux_service import DVAudioMuxService


def test_dv_audio_probe_uses_injected_runner_and_extracts_tracks(tmp_path):
    source = tmp_path / "source.mkv"
    source.write_bytes(b"container")
    calls = []

    def run_fn(cmd, **kwargs):
        calls.append((list(cmd), dict(kwargs)))
        if kwargs.get("return_process"):
            return SimpleNamespace(
                returncode=0,
                stdout='{"streams":[{"index":2,"codec_name":"eac3"}]}',
                stderr="",
            )
        target = tmp_path / "audio_0.eac3"
        target.write_bytes(b"audio")
        return 0

    service = DVAudioMuxService(
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        mp4box_muxer=None,
        log=lambda *_: None,
    )
    tracks = service._extract_audio_tracks(source, tmp_path, run_fn)

    assert len(tracks) == 1
    assert tracks[0].stream_index == 2
    assert tracks[0].codec_name == "eac3"
    assert tracks[0].path == tmp_path / "audio_0.eac3"
    probe_cmd, probe_kwargs = calls[0]
    assert probe_cmd[0] == "ffprobe"
    assert probe_kwargs["return_process"] is True
    assert probe_kwargs["timeout"] == 30


def test_dv_audio_probe_malformed_json_is_safe(tmp_path):
    logs = []

    def run_fn(_cmd, **kwargs):
        assert kwargs.get("return_process") is True
        return SimpleNamespace(returncode=0, stdout="{broken", stderr="")

    service = DVAudioMuxService(
        ffmpeg_path="ffmpeg",
        ffprobe_path="ffprobe",
        mp4box_muxer=None,
        log=lambda message, level="info": logs.append((level, message)),
    )

    tracks = service._extract_audio_tracks(tmp_path / "source.mkv", tmp_path, run_fn)
    assert tracks == []
    assert any("konnte nicht geparst" in message for _, message in logs)
