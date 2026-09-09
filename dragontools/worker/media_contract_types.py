from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class ExpectedAudioTrack:
    codec: str
    channels: int
    language: str = ""


@dataclass(frozen=True, slots=True)
class ExpectedSubtitleTrack:
    codec: str
    language: str = ""
    forced: bool = False


@dataclass(frozen=True, slots=True)
class ExpectedMediaContract:
    container: str
    video_codec: str
    video_stream_count: int
    audio_tracks: tuple[ExpectedAudioTrack, ...]
    subtitle_tracks: tuple[ExpectedSubtitleTrack, ...]
    min_video_bit_depth: int | None = None
    require_hdr: bool = False
    require_dolby_vision: bool = False
    require_hdr10plus: bool = False
    expected_width: int | None = None
    expected_height: int | None = None

    @property
    def audio_stream_count(self) -> int:
        return len(self.audio_tracks)

    @property
    def subtitle_stream_count(self) -> int:
        return len(self.subtitle_tracks)
