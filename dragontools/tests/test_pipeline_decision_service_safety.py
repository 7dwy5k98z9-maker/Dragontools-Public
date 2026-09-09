from __future__ import annotations

from types import SimpleNamespace

import pytest

from dragontools.core.models import MediaInfo, VideoStream
from dragontools.worker.pipeline_decision_service import PipelineDecisionService


class _Settings:
    def value(self, _key, default=None, type=None):
        return default


class _Logger:
    def __init__(self):
        self.messages = []
        self.short_messages = []

    def info(self, message):
        self.messages.append(str(message))

    def info_short(self, message):
        text = str(message)
        self.messages.append(text)
        self.short_messages.append(text)


class _Archive:
    def __init__(self):
        self.calls = []

    def archive_original(self, path, reason):
        self.calls.append((path, reason))


def _media(*, source_codec="hevc", dv=False, hdrplus=False):
    video = VideoStream(
        index=0,
        codec=source_codec,
        width=3840,
        height=2160,
        hdr_format="dolby_vision" if dv else "hdr10plus" if hdrplus else None,
        has_hdr10plus=hdrplus,
        has_dolby_vision=dv,
    )
    return MediaInfo(
        path="film.mkv",
        audio_streams=[],
        subtitle_streams=[],
        video_streams=[video],
        has_hdr10plus=hdrplus,
        dolby_vision=dv,
    )


def _service(*, codec="h265", overrides=None, archive=None, logger=None):
    return PipelineDecisionService(
        codec=codec,
        encoder_options={},
        file_overrides=overrides or {},
        settings=_Settings(),
        logger=logger or _Logger(),
        archive_service=archive,
    )


def test_h265_dv_routes_to_mp4_without_archive():
    archive = _Archive()
    service = _service(archive=archive)

    pipeline, container = service.select_pipeline_context("film.mkv", _media(dv=True))

    assert (pipeline, container) == ("dv", "mp4")
    assert archive.calls == []


def test_incompatible_target_override_archives_and_downgrades_before_worker():
    archive = _Archive()
    logger = _Logger()
    service = _service(
        codec="h264",
        overrides={"film.mkv": {"preserve_dv": True}},
        archive=archive,
        logger=logger,
    )

    pipeline, container = service.select_pipeline_context("film.mkv", _media(dv=True))

    assert (pipeline, container) == ("standard", "mkv")
    assert len(archive.calls) == 1
    assert "Zielcodec H264" in archive.calls[0][1]
    assert any("Zielcodec H264" in message for message in logger.messages)


def test_av1_hdrplus_source_is_archived_instead_of_using_hevc_hdrplus_tool():
    archive = _Archive()
    service = _service(codec="h265", archive=archive)

    pipeline, container = service.select_pipeline_context(
        "film.mkv",
        _media(source_codec="av1", hdrplus=True),
    )

    assert (pipeline, container) == ("standard", "mkv")
    assert len(archive.calls) == 1
    assert "AV1-Quelle" in archive.calls[0][1]


def test_invalid_configured_target_codec_fails_at_service_construction():
    with pytest.raises(ValueError, match="Ziel-Codec"):
        _service(codec="nonsense")


def test_string_false_encoder_option_does_not_force_dv_pipeline():
    logger = _Logger()
    service = PipelineDecisionService(
        codec="h265",
        encoder_options={"preserve_dv": "false", "preserve_hdrplus": "0"},
        file_overrides={},
        settings=_Settings(),
        logger=logger,
        archive_service=_Archive(),
    )

    pipeline, container = service.select_pipeline_context("film.mkv", _media(dv=True))

    assert (pipeline, container) == ("standard", "mkv")
    assert service.last_selection["effective_preserve_dv"] is False


def test_av1_dv_priority_is_logged_as_short_info_without_archive():
    archive = _Archive()
    logger = _Logger()
    service = _service(codec="av1", archive=archive, logger=logger)

    pipeline, container = service.select_pipeline_context(
        "film.mkv",
        _media(source_codec="av1", dv=True, hdrplus=True),
    )

    assert (pipeline, container) == ("av1_dv", "mp4")
    assert archive.calls == []
    assert service.last_selection["effective_preserve_dv"] is True
    assert service.last_selection["effective_preserve_hdrplus"] is False
    assert any("Dolby Vision hat Priorität" in msg for msg in logger.short_messages)
    assert any("HDR10+ wird bewusst nicht erhalten" in msg for msg in logger.short_messages)
