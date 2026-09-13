from __future__ import annotations

from pathlib import Path

from dragontools.core.media_analyzer_streams import (
    _build_audio_streams,
    _build_subtitle_streams,
    _build_video_streams,
)
from dragontools.core.movie_renamer_candidates import (
    _limit_candidates_with_provider_coverage,
    _series_candidate_from_result,
)
from dragontools.core.movie_renamer_models import ParsedSeriesReleaseName, SeriesRenameCandidate


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_block11_facades_stay_small() -> None:
    assert len((PACKAGE_ROOT / "core/media_analyzer_streams.py").read_text(encoding="utf-8").splitlines()) <= 60
    assert len((PACKAGE_ROOT / "core/movie_renamer_candidates.py").read_text(encoding="utf-8").splitlines()) <= 80


def test_block11_stream_builders_keep_public_facade_contract() -> None:
    video = _build_video_streams(
        [{"Format": "HEVC", "Width": "1920", "Height": "1080", "BitDepth": "10", "ColorSpace": "YUV", "ChromaSubsampling": "4:2:0"}],
        [],
        {},
        [],
    )
    audio = _build_audio_streams(
        [{"Format": "AAC", "Language": "German", "StreamOrder": "1"}],
        [{"index": 2, "codec_name": "aac", "tags": {"language": "deu"}}],
    )
    subs = _build_subtitle_streams(
        [{"Format": "UTF-8", "Language": "German", "StreamOrder": "2"}],
        [{"index": 3, "codec_name": "subrip", "tags": {"language": "deu"}}],
    )
    assert video[0].codec == "HEVC"
    assert video[0].pix_fmt == "yuv420p10le"
    assert audio[0].index == 2 and audio[0].language == "de"
    assert subs[0].index == 3 and subs[0].codec == "subrip"


def test_block11_series_fallback_confidence_contract_is_preserved() -> None:
    parsed = ParsedSeriesReleaseName(
        source_name="Kaiju No. 8 - S00E05.mkv",
        suffix=".mkv",
        series="Kaiju No. 8",
        season=0,
        episode=5,
        year=2024,
        warnings=(),
    )
    candidate = _series_candidate_from_result(
        {
            "series": "Kaiju No. 8",
            "season": 0,
            "episode": 5,
            "episode_title": "Folge 05",
            "provider": "tvdb",
            "provider_id": 423075,
            "episode_id": 12345,
            "year": 2024,
        },
        parsed,
        title_exception=lambda value: value,
    )
    assert candidate is not None
    assert candidate.match_reason == "Episodentitel offen"
    assert candidate.score <= 0.92


def test_block11_provider_limit_remains_per_provider() -> None:
    class Client:
        provider_order = ("tvdb", "tmdb")

    candidates = [
        SeriesRenameCandidate("A", 1, 1, "One", 2024, "tvdb", 1, 11, 0.99, ""),
        SeriesRenameCandidate("B", 1, 1, "One", 2024, "tvdb", 2, 12, 0.98, ""),
        SeriesRenameCandidate("C", 1, 1, "One", 2024, "tmdb", 3, 13, 0.97, ""),
        SeriesRenameCandidate("D", 1, 1, "One", 2024, "tmdb", 4, 14, 0.96, ""),
    ]
    selected = _limit_candidates_with_provider_coverage(candidates, client=Client(), limit=1)
    assert [item.provider for item in selected] == ["tvdb", "tmdb"]
