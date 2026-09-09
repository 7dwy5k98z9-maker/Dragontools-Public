# -*- coding: utf-8 -*-
"""Target-path settings used by :mod:`dragontools.gui.convert_widget`.

The service owns codec-specific path-key selection and fallback handling.  It is
Qt-light (QSettings-compatible object only) and deliberately does not know
anything about the widget layout.
"""
from __future__ import annotations

from ..core.paths import default_target_paths, get_tool_paths, invalidate_tool_paths
from ..core.settings import (
    SET_KEY_PATH_H264_TV,
    SET_KEY_PATH_H264_ANIME,
    SET_KEY_PATH_H264_FILME,
    SET_KEY_PATH_H265_TV,
    SET_KEY_PATH_H265_ANIME,
    SET_KEY_PATH_H265_FILME,
    SET_KEY_PATH_AV1_TV,
    SET_KEY_PATH_AV1_ANIME,
    SET_KEY_PATH_AV1_FILME,
    SET_KEY_PATH_TV,
    SET_KEY_PATH_ANIME,
    SET_KEY_PATH_FILME,
)


class ConvertWidgetTargetPathService:
    """Resolve configured TV/Anime/film targets for one converter codec."""

    def __init__(self, *, default_codec: str, settings) -> None:
        self.default_codec = str(default_codec or "")
        self.settings = settings

    def key_map(self) -> dict[str, str]:
        return {
            "h264": {
                "tv": SET_KEY_PATH_H264_TV,
                "anime": SET_KEY_PATH_H264_ANIME,
                "film": SET_KEY_PATH_H264_FILME,
            },
            "h265": {
                "tv": SET_KEY_PATH_H265_TV,
                "anime": SET_KEY_PATH_H265_ANIME,
                "film": SET_KEY_PATH_H265_FILME,
            },
            "av1": {
                "tv": SET_KEY_PATH_AV1_TV,
                "anime": SET_KEY_PATH_AV1_ANIME,
                "film": SET_KEY_PATH_AV1_FILME,
            },
        }.get(
            self.default_codec,
            {
                "tv": SET_KEY_PATH_TV,
                "anime": SET_KEY_PATH_ANIME,
                "film": SET_KEY_PATH_FILME,
            },
        )

    def default_paths(self) -> tuple[str, str, str]:
        defaults = default_target_paths(self.default_codec)
        return defaults["tv"], defaults["anime"], defaults["film"]

    @staticmethod
    def reload_tools():
        invalidate_tool_paths()
        return get_tool_paths()

    def get_target_paths(self) -> dict[str, str]:
        tv_default, anime_default, film_default = self.default_paths()
        key_map = self.key_map()
        raw_tv = self.settings.value(key_map["tv"], "", type=str).strip()
        raw_anime = self.settings.value(key_map["anime"], "", type=str).strip()
        raw_film = self.settings.value(key_map["film"], "", type=str).strip()
        return {
            "tv": raw_tv or tv_default,
            "anime": raw_anime or anime_default,
            "film": raw_film or film_default,
        }
