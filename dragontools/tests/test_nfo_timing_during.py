from __future__ import annotations

from types import SimpleNamespace
import xml.etree.ElementTree as ET


class DummySettings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        if type is bool:
            if isinstance(value, str):
                return value.strip().lower() in {"1", "true", "yes", "on"}
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
        raise AssertionError("movie test must not resolve an episode")


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


def test_nfo_timing_migrates_legacy_enabled_to_after():
    from dragontools.core.settings_postprocess import SET_KEY_NFO_ENABLED
    from dragontools.worker.postprocess_config import config_from_settings

    cfg = config_from_settings(DummySettings({SET_KEY_NFO_ENABLED: True}))

    assert cfg.nfo.enabled is True
    assert cfg.nfo.timing == "after"
    assert cfg.after_conversion_enabled is True


def test_nfo_timing_during_is_not_scheduled_as_after_conversion_work():
    from dragontools.core.settings_postprocess import SET_KEY_NFO_ENABLED, SET_KEY_NFO_TIMING
    from dragontools.worker.postprocess_config import config_from_settings

    cfg = config_from_settings(DummySettings({
        SET_KEY_NFO_ENABLED: True,
        SET_KEY_NFO_TIMING: "during",
    }))

    assert cfg.nfo.enabled is True
    assert cfg.nfo.timing == "during"
    assert cfg.enabled is True
    assert cfg.after_conversion_enabled is False


def test_nfo_timing_off_disables_nfo_even_with_legacy_enabled_flag():
    from dragontools.core.settings_postprocess import SET_KEY_NFO_ENABLED, SET_KEY_NFO_TIMING
    from dragontools.worker.postprocess_config import config_from_settings

    cfg = config_from_settings(DummySettings({
        SET_KEY_NFO_ENABLED: True,
        SET_KEY_NFO_TIMING: "off",
    }))

    assert cfg.nfo.enabled is False
    assert cfg.nfo.timing == "off"


def test_during_nfo_uses_planned_final_video_audio_subtitle_tracks(tmp_path):
    from dragontools.core.models import MediaInfo, VideoStream
    from dragontools.core.settings_postprocess import (
        SET_KEY_NFO_ENABLED,
        SET_KEY_NFO_FILEINFO_ENABLED,
        SET_KEY_NFO_TIMING,
    )
    from dragontools.worker.media_contract_types import (
        ExpectedAudioTrack,
        ExpectedMediaContract,
        ExpectedSubtitleTrack,
    )
    from dragontools.worker.postprocess_runner import PostProcessService

    settings = DummySettings({
        SET_KEY_NFO_ENABLED: True,
        SET_KEY_NFO_TIMING: "during",
        SET_KEY_NFO_FILEINFO_ENABLED: True,
    })
    media = MediaInfo(
        path=str(tmp_path / "Testfilm (2026).mkv"),
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[VideoStream(
            index=0,
            codec="h264",
            width=3840,
            height=2160,
            frame_rate="24000/1001",
        )],
        duration_s=5400.4,
    )
    contract = ExpectedMediaContract(
        container="mkv",
        video_codec="hevc",
        video_stream_count=1,
        audio_tracks=(ExpectedAudioTrack(codec="eac3", channels=6, language="de"),),
        subtitle_tracks=(ExpectedSubtitleTrack(codec="subrip", language="de", forced=False),),
        expected_width=1920,
        expected_height=1080,
    )
    service = PostProcessService(
        settings=settings,
        tools=SimpleNamespace(ffprobe=""),
        log=lambda *_args, **_kwargs: None,
        metadata_session=FakeMetadataSession(_movie_suggestion()),
    )

    output = tmp_path / "Testfilm (2026)_H265.mkv"
    prepared = service.prepare_nfo_during_conversion(
        input_path=str(media.path),
        output_path=str(output),
        final_output_path=str(output),
        media_info=media,
        media_contract=contract,
    )

    assert prepared is not None
    assert prepared.status == "prepared"
    staged = tmp_path / (prepared.staging_path.split("/")[-1])
    # Cross-platform-safe assertion uses the path returned by the service.
    from pathlib import Path
    staged = Path(prepared.staging_path)
    assert staged.exists()

    tree = ET.parse(staged)
    assert tree.findtext("./fileinfo/streamdetails/video/codec") == "hevc"
    assert tree.findtext("./fileinfo/streamdetails/video/width") == "1920"
    assert tree.findtext("./fileinfo/streamdetails/video/height") == "1080"
    assert tree.findtext("./fileinfo/streamdetails/audio/codec") == "eac3"
    assert tree.findtext("./fileinfo/streamdetails/audio/language") == "de"
    assert tree.findtext("./fileinfo/streamdetails/audio/channels") == "6"
    assert tree.findtext("./fileinfo/streamdetails/subtitle/codec") == "subrip"
    assert tree.findtext("./fileinfo/streamdetails/subtitle/language") == "de"

    output.write_bytes(b"video")
    result = service.commit_prepared_nfo(prepared, final_output_path=str(output))
    final_nfo = output.with_suffix(".nfo")
    assert final_nfo.exists()
    assert not staged.exists()
    assert result.created_paths == [str(final_nfo)]
    assert result.items[0]["status"] == "created"


def test_during_mode_does_not_run_nfo_again_after_conversion(tmp_path, monkeypatch):
    from dragontools.core.settings_postprocess import SET_KEY_NFO_ENABLED, SET_KEY_NFO_TIMING
    from dragontools.worker.postprocess_runner import PostProcessService

    video = tmp_path / "film.mkv"
    video.write_bytes(b"video")
    service = PostProcessService(
        settings=DummySettings({
            SET_KEY_NFO_ENABLED: True,
            SET_KEY_NFO_TIMING: "during",
        }),
        tools=SimpleNamespace(ffprobe=""),
        log=lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        service,
        "_create_nfo",
        lambda **_kwargs: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    result = service.run_result(input_path=str(video), output_path=str(video))

    assert result.created_paths == []
    assert result.items == []

def test_quick_toggle_reenables_nfo_from_explicit_off_mode():
    from dragontools.core.settings_postprocess import (
        DEFAULT_NFO_TIMING,
        SET_KEY_NFO_ENABLED,
        SET_KEY_NFO_TIMING,
    )
    from dragontools.gui.convert_widget_quick_settings import (
        QUICK_TOGGLE_SPECS,
        quick_toggle_value,
        set_quick_toggle_value,
    )

    class Settings(DummySettings):
        def setValue(self, key, value):
            self.values[key] = value

        def sync(self):
            return None

    settings = Settings({SET_KEY_NFO_ENABLED: False, SET_KEY_NFO_TIMING: "off"})
    spec = next(item for item in QUICK_TOGGLE_SPECS if item.key == SET_KEY_NFO_ENABLED)

    set_quick_toggle_value(settings, spec, True)

    assert settings.values[SET_KEY_NFO_ENABLED] is True
    assert settings.values[SET_KEY_NFO_TIMING] == DEFAULT_NFO_TIMING
    assert quick_toggle_value(settings, spec) is True
