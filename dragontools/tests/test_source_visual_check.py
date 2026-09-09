from __future__ import annotations


def _frame(width: int, height: int, rgb: tuple[int, int, int]) -> bytes:
    return bytes(rgb) * (width * height)


def test_source_visual_check_blocks_when_enough_probes_are_suspicious(tmp_path, monkeypatch):
    from dragontools.worker.source_visual_check import (
        SourceVisualCheckService,
        SourceVisualCheckSettings,
    )

    video = tmp_path / "defekt.mkv"
    video.write_bytes(b"video")
    settings = SourceVisualCheckSettings(
        enabled=True,
        interval_percent=20,
        sample_duration_s=1,
        fps=1,
        block_percent=80,
        min_hits=4,
    )
    service = SourceVisualCheckService(ffmpeg_path="ffmpeg", ffprobe_path="ffprobe")
    monkeypatch.setattr(service, "_probe_duration", lambda _path: 100.0)
    monkeypatch.setattr(
        service,
        "_read_probe_frames",
        lambda _path, _start, cfg: _frame(cfg.analysis_width, cfg.analysis_height, (180, 20, 180)),
    )

    result = service.check(video, settings)

    assert result.blocked is True
    assert result.suspicious_count == 4
    assert "blockiert" in result.summary_line()


def test_source_visual_check_does_not_block_single_black_scene(tmp_path, monkeypatch):
    from dragontools.worker.source_visual_check import (
        SourceVisualCheckService,
        SourceVisualCheckSettings,
    )

    video = tmp_path / "film.mkv"
    video.write_bytes(b"video")
    settings = SourceVisualCheckSettings(
        enabled=True,
        interval_percent=20,
        sample_duration_s=1,
        fps=1,
        block_percent=80,
        min_hits=4,
    )
    service = SourceVisualCheckService(ffmpeg_path="ffmpeg", ffprobe_path="ffprobe")
    monkeypatch.setattr(service, "_probe_duration", lambda _path: 100.0)

    def fake_frames(_path, start, cfg):
        if start < 25:
            return _frame(cfg.analysis_width, cfg.analysis_height, (0, 0, 0))
        return _frame(cfg.analysis_width, cfg.analysis_height, (80, 80, 80))

    monkeypatch.setattr(service, "_read_probe_frames", fake_frames)

    result = service.check(video, settings)

    assert result.blocked is False
    assert result.suspicious_count == 1


def test_source_visual_settings_reads_qsettings_values():
    from dragontools.core.settings import (
        SET_KEY_SOURCE_VISUAL_CHECK_BLOCK_PERCENT,
        SET_KEY_SOURCE_VISUAL_CHECK_ENABLED,
        SET_KEY_SOURCE_VISUAL_CHECK_FPS,
        SET_KEY_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT,
        SET_KEY_SOURCE_VISUAL_CHECK_MIN_HITS,
        SET_KEY_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S,
    )
    from dragontools.worker.source_visual_check import source_visual_settings_from_qsettings

    class DummySettings:
        def __init__(self, values):
            self.values = dict(values)

        def value(self, key, default=None, type=None):
            value = self.values.get(key, default)
            if type is not None:
                return type(value)
            return value

    settings = source_visual_settings_from_qsettings(DummySettings({
        SET_KEY_SOURCE_VISUAL_CHECK_ENABLED: True,
        SET_KEY_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT: 10,
        SET_KEY_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S: 2,
        SET_KEY_SOURCE_VISUAL_CHECK_FPS: 3,
        SET_KEY_SOURCE_VISUAL_CHECK_BLOCK_PERCENT: 85,
        SET_KEY_SOURCE_VISUAL_CHECK_MIN_HITS: 5,
    }))

    assert settings.enabled is True
    assert settings.interval_percent == 10
    assert settings.sample_duration_s == 2
    assert settings.fps == 3
    assert settings.block_percent == 85
    assert settings.min_hits == 5
