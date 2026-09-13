# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtWidgets import QWidget

from ..core.audio_video_matcher import CutMatchResult, TimeMappingResult
from ..worker.audio_video_match_thread import AudioVideoMatchThread
from .audio_video_matcher_paths import AudioVideoMatcherPathsMixin
from .audio_video_matcher_results import AudioVideoMatcherResultsMixin
from .audio_video_matcher_runtime import AudioVideoMatcherRuntimeMixin
from .audio_video_matcher_view import AudioVideoMatcherViewMixin


class AudioVideoMatcherWidget(
    AudioVideoMatcherPathsMixin,
    AudioVideoMatcherRuntimeMixin,
    AudioVideoMatcherResultsMixin,
    AudioVideoMatcherViewMixin,
    QWidget,
):
    """GUI facade for audio/video matching and synchronization."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: AudioVideoMatchThread | None = None
        self._analysis: TimeMappingResult | None = None
        self._cut_results: list[CutMatchResult] = []
        self._init_ui()

    def iter_shutdown_workers(self) -> tuple:
        """Explicit main-window shutdown contract kept on the facade."""
        return AudioVideoMatcherRuntimeMixin.iter_shutdown_workers(self)
