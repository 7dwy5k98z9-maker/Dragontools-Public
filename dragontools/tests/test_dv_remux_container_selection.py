# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from dragontools.worker import dv_remux_components as components
from dragontools.worker import dv_subtitle_mux_service as subtitle_mux


def _noop(*_args, **_kwargs):
    return None


def test_dv_output_manager_uses_selected_mkv_suffix(tmp_path):
    worker = SimpleNamespace(
        overwrite_original=False,
        container="mkv",
        log=_noop,
        _log=_noop,
    )
    manager = components.DVOutputManager(worker)
    source = tmp_path / "Film.mp4"

    output = Path(manager.build_output_path(str(source)))

    assert output == tmp_path / "Film_DV_Remux.mkv"


def test_dv_output_manager_overwrite_uses_selected_mkv_suffix(tmp_path):
    worker = SimpleNamespace(
        overwrite_original=True,
        container="mkv",
        log=_noop,
        _log=_noop,
    )
    manager = components.DVOutputManager(worker)
    source = tmp_path / "Film.mp4"

    output = Path(manager.build_output_path(str(source)))

    assert output == tmp_path / "__temp_dv_remux__" / "Film.mkv"


def test_dv_remux_audio_plan_receives_mkv_and_uses_mka(monkeypatch):
    captured = {}
    stream = SimpleNamespace(index=2, codec="truehd", language="de")
    decision = SimpleNamespace(
        stream=stream,
        needs_transcode=False,
        target_codec="truehd",
        target_channels=8,
        target_bitrate=4_000_000,
        drc_scale=None,
    )

    def fake_plan(*, audio_streams, file_override, container):
        captured["container"] = container
        return [decision]

    monkeypatch.setattr(components, "compute_audio_track_plan", fake_plan)
    monkeypatch.setattr(components, "build_audio_title", lambda **_kwargs: "Deutsch TrueHD 7.1")

    worker = SimpleNamespace(container="mkv", log=_noop)
    pipeline = components.DVMP4BoxPipelineRunner(worker, SimpleNamespace())
    jobs = pipeline.build_audio_jobs(SimpleNamespace(audio_streams=[stream]), {})

    assert captured["container"] == "mkv"
    assert jobs == [
        {
            "stream_index": 2,
            "mode": "copy",
            "codec": "truehd",
            "ext": ".mka",
            "language": "de",
            "title": "Deutsch TrueHD 7.1",
        }
    ]


def test_dv_remux_mkv_mux_uses_mkvmerge(tmp_path):
    video = tmp_path / "video.hevc"
    audio = tmp_path / "audio.mka"
    output = tmp_path / "Film.mkv"
    video.write_bytes(b"video")
    audio.write_bytes(b"audio")
    seen = {}

    class Runner:
        def run_abortable_capture(self, cmd, *, timeout_s=None):
            seen["cmd"] = list(cmd)
            seen["timeout_s"] = timeout_s
            output.write_bytes(b"mkv")
            return 0, "", ""

    worker = SimpleNamespace(
        container="mkv",
        tools=SimpleNamespace(mkvmerge="mkvmerge", mp4box="MP4Box"),
        abort_requested=False,
        _last_stderr="",
        log=_noop,
    )
    pipeline = components.DVMP4BoxPipelineRunner(worker, Runner())

    ok = pipeline.mux(
        str(video),
        [(str(audio), {"language": "de", "title": "Deutsch TrueHD 7.1"})],
        str(output),
    )

    assert ok is True
    assert seen["cmd"][:4] == ["mkvmerge", "-o", str(output), str(video)]
    assert "--language" in seen["cmd"]
    assert "0:de" in seen["cmd"]
    assert "--track-name" in seen["cmd"]
    assert seen["timeout_s"] is not None


def test_dv_remux_mp4_mux_still_uses_mp4box(tmp_path):
    video = tmp_path / "video.hevc"
    output = tmp_path / "Film.mp4"
    video.write_bytes(b"video")
    seen = {}

    class Runner:
        def run_abortable_capture(self, cmd, *, timeout_s=None):
            seen["cmd"] = list(cmd)
            output.write_bytes(b"mp4")
            return 0, "", ""

    worker = SimpleNamespace(
        container="mp4",
        tools=SimpleNamespace(mkvmerge="mkvmerge", mp4box="MP4Box"),
        abort_requested=False,
        _last_stderr="",
        log=_noop,
    )
    pipeline = components.DVMP4BoxPipelineRunner(worker, Runner())

    ok = pipeline.mux(str(video), [], str(output))

    assert ok is True
    assert seen["cmd"][0] == "MP4Box"
    assert f"{video}:dvp=8.1.hdr10" in seen["cmd"]



def test_dv_remux_subtitle_storage_is_sidecar_for_mp4_and_internal_for_mkv():
    assert components.dv_remux_subtitle_storage("mp4") == "sidecar"
    assert components.dv_remux_subtitle_storage("mkv") == "internal"
    assert components.dv_remux_subtitle_storage(None) == "sidecar"


def test_dv_remux_mkv_builds_internal_subtitle_jobs_and_preserves_burn_candidate(monkeypatch):
    forced = SimpleNamespace(
        index=5,
        codec="subrip",
        language="deu",
        title="Deutsch Forced",
        forced=True,
    )
    regular = SimpleNamespace(
        index=6,
        codec="ass",
        language="de",
        title="Deutsch",
        forced=False,
    )
    plan = SimpleNamespace(
        keep_streams=(regular,),
        burn_sub=forced,
        burn_warnings=(),
    )
    captured = {}

    def fake_plan(*args, **kwargs):
        captured.update(kwargs)
        return plan

    monkeypatch.setattr(subtitle_mux, "compute_subtitle_plan", fake_plan)
    service = subtitle_mux.DVSubtitleMuxService(
        ffmpeg_path="ffmpeg",
        subtitle_rules={"dv_extract_external_subs": False},
        log=_noop,
    )
    media = SimpleNamespace(subtitle_streams=[forced, regular], audio_streams=[], duration_s=123.0)

    jobs = service.build_internal_jobs(media, {}, preserve_burn_candidate=True)

    assert captured["container_copy_supported"] is True
    assert [job.stream_index for job in jobs] == [5, 6]
    assert jobs[0].language == "de"
    assert jobs[0].forced is True
    assert jobs[0].ext == ".srt"
    assert jobs[1].forced is False
    # dv_extract_external_subs only controls the MP4 sidecar path; it must not
    # disable internal subtitles for Matroska.
    assert len(jobs) == 2


def test_dv_remux_mkv_mux_writes_subtitle_language_title_and_forced_flag(tmp_path):
    video = tmp_path / "video.hevc"
    subtitle = tmp_path / "forced.srt"
    output = tmp_path / "Film.mkv"
    video.write_bytes(b"video")
    subtitle.write_text("1\n00:00:00,000 --> 00:00:01,000\nTest\n", encoding="utf-8")
    seen = {}

    class Runner:
        def run_abortable_capture(self, cmd, *, timeout_s=None):
            seen["cmd"] = list(cmd)
            output.write_bytes(b"mkv")
            return 0, "", ""

    worker = SimpleNamespace(
        container="mkv",
        tools=SimpleNamespace(mkvmerge="mkvmerge", mp4box="MP4Box"),
        abort_requested=False,
        _last_stderr="",
        log=_noop,
    )
    pipeline = components.DVMP4BoxPipelineRunner(worker, Runner())

    ok = pipeline.mux(
        str(video),
        [],
        str(output),
        [
            subtitle_mux.DVMuxSubtitleTrack(
                path=subtitle,
                stream_index=5,
                codec="subrip",
                language="de",
                title="Deutsch Forced",
                forced=True,
            )
        ],
    )

    assert ok is True
    cmd = seen["cmd"]
    assert "--language" in cmd and "0:de" in cmd
    assert "--track-name" in cmd and "0:Deutsch Forced" in cmd
    assert "--forced-display-flag" in cmd and "0:yes" in cmd
    assert str(subtitle) in cmd


def test_dv_remux_mp4_mux_does_not_embed_subtitle_tracks(tmp_path):
    video = tmp_path / "video.hevc"
    subtitle = tmp_path / "forced.srt"
    output = tmp_path / "Film.mp4"
    video.write_bytes(b"video")
    subtitle.write_text("dummy", encoding="utf-8")
    seen = {}

    class Runner:
        def run_abortable_capture(self, cmd, *, timeout_s=None):
            seen["cmd"] = list(cmd)
            output.write_bytes(b"mp4")
            return 0, "", ""

    worker = SimpleNamespace(
        container="mp4",
        tools=SimpleNamespace(mkvmerge="mkvmerge", mp4box="MP4Box"),
        abort_requested=False,
        _last_stderr="",
        log=_noop,
    )
    pipeline = components.DVMP4BoxPipelineRunner(worker, Runner())

    ok = pipeline.mux(
        str(video),
        [],
        str(output),
        [
            subtitle_mux.DVMuxSubtitleTrack(
                path=subtitle,
                stream_index=5,
                codec="subrip",
                language="de",
                title="",
                forced=True,
            )
        ],
    )

    assert ok is True
    assert str(subtitle) not in seen["cmd"]
    assert "--forced-display-flag" not in seen["cmd"]


def test_standard_dv_mkv_does_not_duplicate_actual_burn_in_subtitle(monkeypatch):
    """Standard-DV keeps normal tracks internal but does not duplicate a burn-in track."""
    forced = SimpleNamespace(
        index=5,
        codec="subrip",
        language="de",
        title="Deutsch Forced",
        forced=True,
    )
    regular = SimpleNamespace(
        index=6,
        codec="ass",
        language="de",
        title="Deutsch",
        forced=False,
    )
    monkeypatch.setattr(
        subtitle_mux,
        "compute_subtitle_plan",
        lambda *args, **kwargs: SimpleNamespace(
            keep_streams=(regular,), burn_sub=forced, burn_warnings=()
        ),
    )
    service = subtitle_mux.DVSubtitleMuxService(
        ffmpeg_path="ffmpeg", subtitle_rules={}, log=_noop
    )
    media = SimpleNamespace(
        subtitle_streams=[forced, regular], audio_streams=[], duration_s=120.0
    )

    jobs = service.build_internal_jobs(media, {}, preserve_burn_candidate=False)

    assert [job.stream_index for job in jobs] == [6]


def test_standard_dv_mkv_muxer_embeds_selected_subtitle(tmp_path):
    from dragontools.worker.dv_mkv_muxer import DVMKVMuxer

    video = tmp_path / "injected.hevc"
    subtitle = tmp_path / "subtitle.srt"
    output = tmp_path / "out.mkv"
    video.write_bytes(b"video")
    subtitle.write_text("dummy", encoding="utf-8")
    seen = {}

    def run_fn(cmd):
        seen["cmd"] = list(cmd)
        output.write_bytes(b"mkv")
        return 0

    muxer = DVMKVMuxer(
        mkvmerge_path="mkvmerge", audio_track_name=lambda _meta: ""
    )
    ok = muxer.mux_final_output(
        run_fn,
        output_path=str(output),
        injected_hevc=video,
        mux_tracks=[],
        subtitle_tracks=[
            subtitle_mux.DVMuxSubtitleTrack(
                path=subtitle,
                stream_index=3,
                codec="subrip",
                language="de",
                title="Deutsch Forced",
                forced=True,
            )
        ],
    )

    assert ok is True
    assert str(subtitle) in seen["cmd"]
    assert "0:de" in seen["cmd"]
    assert "0:Deutsch Forced" in seen["cmd"]
    assert "0:yes" in seen["cmd"]


def test_standard_dv_subtitle_stage_routes_mp4_to_sidecar_and_mkv_internal(tmp_path):
    from dragontools.worker.dv_pipeline_stages import DVPipelineStages

    calls = []

    class TempState:
        failure_reason = ""
        failure_stage = ""

        def record_failure(self, *, reason, stage):
            self.failure_reason = reason
            self.failure_stage = stage

    class InternalService:
        def prepare_internal_mkv_tracks(self, **kwargs):
            calls.append(kwargs)
            return True, ["internal-track"]

    stages = DVPipelineStages(
        tools=SimpleNamespace(),
        encoder_config=None,
        progress_runner=None,
        temp_state=TempState(),
        audio_mux_service=None,
        mp4box_muxer=None,
        mkv_muxer=None,
        hdr10plus_service=None,
        level5_editor=None,
        subtitle_service=None,
        subtitle_mux_service=InternalService(),
        log=_noop,
        verbose_log=_noop,
        assert_nonempty_file=lambda *_args: True,
        clear_burn_sub_tmp=_noop,
    )
    runner = SimpleNamespace(adapter=lambda **_kwargs: (lambda _cmd: 0))

    mp4_state = SimpleNamespace(
        request=SimpleNamespace(container="mp4"), mux_subtitle_tracks=["old"]
    )
    assert stages._prepare_subtitles(mp4_state, runner) is True
    assert mp4_state.mux_subtitle_tracks == []
    assert calls == []

    mkv_state = SimpleNamespace(
        request=SimpleNamespace(
            container="mkv", input_path="source.mkv", media_info=object(), override={}
        ),
        files=SimpleNamespace(root=tmp_path),
        mux_subtitle_tracks=[],
    )
    assert stages._prepare_subtitles(mkv_state, runner) is True
    assert mkv_state.mux_subtitle_tracks == ["internal-track"]
    assert len(calls) == 1
