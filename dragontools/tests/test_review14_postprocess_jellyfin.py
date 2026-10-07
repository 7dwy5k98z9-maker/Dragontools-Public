from __future__ import annotations

import threading
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from types import SimpleNamespace


class DummySettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is bool:
            return bool(value)
        if type is str:
            return str(value)
        if type is int:
            return int(value)
        return value

    def contains(self, key):
        return key in self.values


class FakeMetadataSession:
    def __init__(self, suggestion):
        self.suggestion = suggestion

    def resolve_movie(self, path, *, require_unambiguous=False):
        return SimpleNamespace(suggestion=self.suggestion, reason="")

    def resolve_episode(self, path, *, require_unambiguous=False):
        raise AssertionError("movie fixture must not resolve an episode")


def _movie_suggestion():
    from dragontools.core.online_metadata import MovieMetadataSuggestion

    return MovieMetadataSuggestion(
        query_title="Testfilm",
        query_year=2026,
        tmdb_id=123,
        title="Testfilm",
        original_title="Test Movie",
        release_year=2026,
    )


def test_during_nfo_refresh_prefers_actual_verified_output_streams(tmp_path, monkeypatch):
    from dragontools.core.settings_postprocess import (
        SET_KEY_NFO_ENABLED,
        SET_KEY_NFO_FILEINFO_ENABLED,
        SET_KEY_NFO_TIMING,
    )
    from dragontools.worker.media_contract_types import ExpectedAudioTrack, ExpectedMediaContract
    from dragontools.worker.postprocess_runner import PostProcessService
    import dragontools.core.jellyfin_nfo as nfo_module

    settings = DummySettings({
        SET_KEY_NFO_ENABLED: True,
        SET_KEY_NFO_TIMING: "during",
        SET_KEY_NFO_FILEINFO_ENABLED: True,
    })
    service = PostProcessService(
        settings=settings,
        tools=SimpleNamespace(ffprobe="ffprobe"),
        log=lambda *_args, **_kwargs: None,
        metadata_session=FakeMetadataSession(_movie_suggestion()),
    )
    contract = ExpectedMediaContract(
        container="mkv",
        video_codec="hevc",
        video_stream_count=1,
        audio_tracks=(ExpectedAudioTrack(codec="aac", channels=2, language="de"),),
        subtitle_tracks=(),
        expected_width=1920,
        expected_height=1080,
    )
    media = SimpleNamespace(
        primary_video=SimpleNamespace(width=3840, height=2160, frame_rate="24000/1001", duration_s=90),
        duration_s=90,
    )
    output = tmp_path / "Testfilm (2026).mkv"
    prepared = service.prepare_nfo_during_conversion(
        input_path=str(output),
        output_path=str(output),
        final_output_path=str(output),
        media_info=media,
        media_contract=contract,
    )
    assert prepared is not None
    assert ET.parse(prepared.staging_path).findtext("./fileinfo/streamdetails/audio/codec") == "aac"

    output.write_bytes(b"verified-output")

    def actual_fileinfo(_video_path, _ffprobe_path):
        root = ET.Element("fileinfo")
        details = ET.SubElement(root, "streamdetails")
        video = ET.SubElement(details, "video")
        ET.SubElement(video, "codec").text = "hevc"
        audio = ET.SubElement(details, "audio")
        ET.SubElement(audio, "codec").text = "eac3"
        ET.SubElement(audio, "language").text = "deu"
        ET.SubElement(audio, "channels").text = "6"
        return root

    monkeypatch.setattr(nfo_module, "build_fileinfo", actual_fileinfo)
    refreshed = service.refresh_prepared_nfo(
        prepared,
        media_info=media,
        media_contract=contract,
        video_path=str(output),
    )

    assert refreshed is prepared
    tree = ET.parse(prepared.staging_path)
    assert tree.findtext("./fileinfo/streamdetails/audio/codec") == "eac3"
    assert tree.findtext("./fileinfo/streamdetails/audio/language") == "deu"
    assert tree.findtext("./fileinfo/streamdetails/audio/channels") == "6"


def test_build_fileinfo_ignores_attached_picture_video_stream(tmp_path, monkeypatch):
    from dragontools.core import jellyfin_nfo

    video = tmp_path / "movie.mkv"
    video.write_bytes(b"x")
    payload = {
        "format": {"duration": "120.0", "bit_rate": "5000000"},
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "hevc",
                "width": 1920,
                "height": 1080,
                "avg_frame_rate": "24/1",
                "disposition": {"attached_pic": 0},
            },
            {
                "index": 1,
                "codec_type": "video",
                "codec_name": "mjpeg",
                "width": 1000,
                "height": 1000,
                "avg_frame_rate": "0/0",
                "disposition": {"attached_pic": 1},
            },
        ],
    }

    monkeypatch.setattr(
        jellyfin_nfo.subprocess,
        "run",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout=__import__("json").dumps(payload)),
    )
    fileinfo = jellyfin_nfo.build_fileinfo(video, "ffprobe")

    assert fileinfo is not None
    videos = fileinfo.findall("./streamdetails/video")
    assert len(videos) == 1
    assert videos[0].findtext("codec") == "hevc"


def test_trickplay_limiter_does_not_reset_permits_when_limit_changes():
    from dragontools.worker.trickplay_concurrency import (
        reset_trickplay_concurrency_for_tests,
        trickplay_semaphore,
    )

    reset_trickplay_concurrency_for_tests()
    first_entered = threading.Event()
    release_first = threading.Event()
    second_attempting = threading.Event()
    second_entered = threading.Event()

    def first():
        with trickplay_semaphore(1):
            first_entered.set()
            release_first.wait(2)

    def second():
        second_attempting.set()
        with trickplay_semaphore(2):
            second_entered.set()

    t1 = threading.Thread(target=first)
    t2 = threading.Thread(target=second)
    t1.start()
    assert first_entered.wait(1)
    t2.start()
    assert second_attempting.wait(1)
    assert not second_entered.wait(0.1)
    release_first.set()
    assert second_entered.wait(1)
    t1.join(1)
    t2.join(1)
    reset_trickplay_concurrency_for_tests()


def test_trickplay_zero_byte_jpeg_is_not_accepted_as_success(tmp_path, monkeypatch):
    from dragontools.worker.trickplay_service import TrickplayGenerator, TrickplaySettings

    video = tmp_path / "Film.mkv"
    video.write_bytes(b"video")
    settings = TrickplaySettings(enabled=True, hwaccel="none")

    def fake_run(self, cmd):
        output_pattern = Path(cmd[-1])
        output_pattern.parent.mkdir(parents=True, exist_ok=True)
        (output_pattern.parent / "0.jpg").write_bytes(b"")
        return True

    monkeypatch.setattr(TrickplayGenerator, "_run", fake_run)
    generator = TrickplayGenerator(ffmpeg_path="ffmpeg", log=lambda *_args: None)

    assert generator.generate(video, settings) is None
    assert not (tmp_path / "Film.trickplay").exists()


def test_trickplay_skip_repairs_existing_empty_variant_after_new_render(tmp_path, monkeypatch):
    from dragontools.worker.trickplay_service import TrickplayGenerator, TrickplaySettings

    video = tmp_path / "Film.mkv"
    video.write_bytes(b"video")
    invalid = tmp_path / "Film.trickplay" / "320 - 10x10"
    invalid.mkdir(parents=True)
    settings = TrickplaySettings(enabled=True, conflict_mode="skip", hwaccel="none")

    def fake_run(self, cmd):
        output_pattern = Path(cmd[-1])
        output_pattern.parent.mkdir(parents=True, exist_ok=True)
        (output_pattern.parent / "0.jpg").write_bytes(b"jpeg")
        return True

    monkeypatch.setattr(TrickplayGenerator, "_run", fake_run)
    generator = TrickplayGenerator(ffmpeg_path="ffmpeg", log=lambda *_args: None)

    root = generator.generate(video, settings)

    assert root == tmp_path / "Film.trickplay"
    assert (invalid / "0.jpg").read_bytes() == b"jpeg"


def test_failed_conversion_discards_prepared_nfo_without_refreshing_failed_output(tmp_path):
    from concurrent.futures import Future
    from dragontools.worker.postprocess_models import PreparedNfo
    from dragontools.worker.workflow_postprocess_commit import WorkflowPostprocessCommitService

    staging = tmp_path / ".pending.nfo"
    staging.write_text("pending", encoding="utf-8")
    prepared = PreparedNfo(
        staging_path=str(staging),
        target_path=str(tmp_path / "film.nfo"),
        conflict_mode="overwrite",
        kind="movie",
        suggestion=object(),
    )
    future = Future()
    future.set_result(prepared)
    calls = []

    class Service:
        def refresh_prepared_nfo(self, *_args, **_kwargs):
            raise AssertionError("failed output must not be refreshed/probed")

        def discard_prepared_nfo(self, item):
            calls.append(item)
            Path(item.staging_path).unlink(missing_ok=True)

    ctx = SimpleNamespace(
        nfo_prepare_future=future,
        prepared_nfo=None,
        analysis=None,
        expected_media_contract=None,
        output_path=str(tmp_path / "broken.mkv"),
    )
    workflow = WorkflowPostprocessCommitService(
        logger=SimpleNamespace(warn=lambda *_args: None),
        result_service=None,
        sidecar_outputs={},
        postprocess_outputs={},
        service=Service(),
        coordinator=None,
    )

    workflow.discard_prepared_nfo(ctx)

    assert calls == [prepared]
    assert not staging.exists()
    assert not (tmp_path / "film.nfo").exists()


def test_async_postprocess_retires_completed_futures(tmp_path):
    from dragontools.worker.postprocess_async import AsyncPostProcessCoordinator
    from dragontools.worker.postprocess_models import PostProcessRunResult

    class FakeService:
        def run_result(self, *, input_path, output_path):
            return PostProcessRunResult([], [])

    coordinator = AsyncPostProcessCoordinator(
        settings=DummySettings(),
        tools=SimpleNamespace(),
        log=lambda *_args: None,
        service_factory=FakeService,
    )
    assert coordinator.submit(
        input_path="input.mkv",
        output_path=str(tmp_path / "output.mkv"),
        existing_sidecars=[],
        sidecar_outputs={},
        postprocess_outputs={},
        result_service=None,
    ) is True
    coordinator.wait_for_all()

    assert coordinator._futures == []


def test_nfo_skip_conflict_is_atomic_across_concurrent_postprocess_jobs(tmp_path, monkeypatch):
    import dragontools.worker.postprocess_runner as module
    from dragontools.worker.postprocess_models import NfoSettings

    output = tmp_path / "Testfilm (2026).mkv"
    output.write_bytes(b"video")
    suggestion = _movie_suggestion()
    first_writer_entered = threading.Event()
    release_first_writer = threading.Event()
    writer_calls: list[Path] = []
    writer_guard = threading.Lock()

    def fake_write_movie_nfo(path, _suggestion, **_kwargs):
        candidate = Path(path)
        with writer_guard:
            writer_calls.append(candidate)
            call_no = len(writer_calls)
        if call_no == 1:
            first_writer_entered.set()
            assert release_first_writer.wait(2)
        candidate.write_text(f"writer-{call_no}", encoding="utf-8")
        return candidate

    monkeypatch.setattr(module, "write_movie_nfo", fake_write_movie_nfo)
    cfg = NfoSettings(enabled=True, include_fileinfo=False, conflict_mode="skip")

    def make_service():
        return module.PostProcessService(
            settings=DummySettings(),
            tools=SimpleNamespace(ffprobe=""),
            log=lambda *_args, **_kwargs: None,
            metadata_session=FakeMetadataSession(suggestion),
        )

    results: list[Path | None] = []

    def run_job():
        results.append(make_service()._create_nfo(
            input_path=str(output),
            output_path=output,
            cfg=cfg,
        ))

    first = threading.Thread(target=run_job)
    second = threading.Thread(target=run_job)
    first.start()
    assert first_writer_entered.wait(1)
    second.start()

    # The second DragonTools job must block at the target lock.  Once the first
    # publishes the NFO it re-plans and observes the existing target as "skip".
    assert len(writer_calls) == 1
    release_first_writer.set()
    first.join(2)
    second.join(2)

    assert not first.is_alive() and not second.is_alive()
    assert len(writer_calls) == 1
    assert output.with_suffix(".nfo").read_text(encoding="utf-8") == "writer-1"
    assert results == [output.with_suffix(".nfo"), output.with_suffix(".nfo")]


def test_trickplay_same_target_jobs_are_serialized(tmp_path, monkeypatch):
    from dragontools.worker.trickplay_concurrency import reset_trickplay_concurrency_for_tests
    from dragontools.worker.trickplay_service import TrickplayGenerator, TrickplaySettings

    reset_trickplay_concurrency_for_tests()
    video = tmp_path / "Film.mkv"
    video.write_bytes(b"video")
    settings = TrickplaySettings(enabled=True, conflict_mode="overwrite", max_jobs=2)
    first_entered = threading.Event()
    release_first = threading.Event()
    second_entered = threading.Event()
    calls = 0
    calls_guard = threading.Lock()

    def fake_generate_locked(self, _video, _settings, final_root, _final_sprite_dir):
        nonlocal calls
        with calls_guard:
            calls += 1
            call_no = calls
        if call_no == 1:
            first_entered.set()
            assert release_first.wait(2)
        else:
            second_entered.set()
        return final_root

    monkeypatch.setattr(TrickplayGenerator, "_generate_locked", fake_generate_locked)
    generator = TrickplayGenerator(ffmpeg_path="ffmpeg", log=lambda *_args: None)
    results: list[Path | None] = []

    def run_job():
        results.append(generator.generate(video, settings))

    first = threading.Thread(target=run_job)
    second = threading.Thread(target=run_job)
    first.start()
    assert first_entered.wait(1)
    second.start()
    assert not second_entered.wait(0.1)
    release_first.set()
    assert second_entered.wait(1)
    first.join(2)
    second.join(2)

    assert calls == 2
    assert results == [tmp_path / "Film.trickplay", tmp_path / "Film.trickplay"]
    reset_trickplay_concurrency_for_tests()
