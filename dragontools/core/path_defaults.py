# -*- coding: utf-8 -*-
"""Standard-Speicherorte und Ausgabeordner von DragonTools."""
from __future__ import annotations

import os
from pathlib import Path

DEFAULT_DOCUMENTS_DIRNAME = "DragonTools"
DEFAULT_OUTPUT_DIRNAME = "Ausgabe"
DEFAULT_CODEC_DIRS = {
    "h264": "H264",
    "h265": "H265",
    "av1": "AV1",
}
DEFAULT_MEDIA_TYPE_DIRS = {
    "tv": "TV",
    "anime": "Anime",
    "film": "Filme",
}

def app_documents_dir(root: str | os.PathLike[str] | None = None) -> Path:
    """Zentraler DragonTools-Dokumentordner.

    Standard: ``%USERPROFILE%\\Documents\\DragonTools``. Tests können über
    ``root`` einen temporären Basisordner übergeben.
    """
    base = Path(root) if root is not None else Path.home() / "Documents" / DEFAULT_DOCUMENTS_DIRNAME
    return base.expanduser().resolve()


def default_output_base(root: str | os.PathLike[str] | None = None, *, create: bool = True) -> Path:
    path = app_documents_dir(root) / DEFAULT_OUTPUT_DIRNAME
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def default_target_path(
    codec: str,
    media_type: str,
    root: str | os.PathLike[str] | None = None,
    *,
    create: bool = True,
) -> Path:
    """Standard-Zielordner für einen Codec und Medientyp.

    Beispiele:
      ``Dokumente/DragonTools/Ausgabe/H265/TV``
      ``Dokumente/DragonTools/Ausgabe/AV1/Filme``
    """
    codec_key = (codec or "h265").lower()
    media_key = (media_type or "film").lower()
    codec_dir = DEFAULT_CODEC_DIRS.get(codec_key, codec_key.upper() or "H265")
    media_dir = DEFAULT_MEDIA_TYPE_DIRS.get(media_key, media_key.capitalize() or "Filme")
    path = default_output_base(root, create=create) / codec_dir / media_dir
    if create:
        path.mkdir(parents=True, exist_ok=True)
    return path


def default_target_paths(
    codec: str,
    root: str | os.PathLike[str] | None = None,
    *,
    create: bool = True,
) -> dict[str, str]:
    """Standard-Zielpfade für TV, Anime und Filme eines Codecs."""
    return {
        media_type: str(default_target_path(codec, media_type, root, create=create))
        for media_type in ("tv", "anime", "film")
    }


def default_target_path_for_settings_key(
    settings_key: str,
    root: str | os.PathLike[str] | None = None,
    *,
    create: bool = True,
) -> str:
    """Standard-Zielpfad passend zu einem QSettings-Key.

    Bewusst als String, weil die GUI/QSettings-Schicht ebenfalls Strings nutzt.
    """
    from .settings import (
        SET_KEY_PATH_ANIME,
        SET_KEY_PATH_AV1_ANIME,
        SET_KEY_PATH_AV1_FILME,
        SET_KEY_PATH_AV1_TV,
        SET_KEY_PATH_FILME,
        SET_KEY_PATH_H264_ANIME,
        SET_KEY_PATH_H264_FILME,
        SET_KEY_PATH_H264_TV,
        SET_KEY_PATH_H265_ANIME,
        SET_KEY_PATH_H265_FILME,
        SET_KEY_PATH_H265_TV,
        SET_KEY_PATH_TV,
    )

    key_map = {
        SET_KEY_PATH_H264_TV: ("h264", "tv"),
        SET_KEY_PATH_H264_ANIME: ("h264", "anime"),
        SET_KEY_PATH_H264_FILME: ("h264", "film"),
        SET_KEY_PATH_H265_TV: ("h265", "tv"),
        SET_KEY_PATH_H265_ANIME: ("h265", "anime"),
        SET_KEY_PATH_H265_FILME: ("h265", "film"),
        SET_KEY_PATH_AV1_TV: ("av1", "tv"),
        SET_KEY_PATH_AV1_ANIME: ("av1", "anime"),
        SET_KEY_PATH_AV1_FILME: ("av1", "film"),
        SET_KEY_PATH_TV: ("h265", "tv"),
        SET_KEY_PATH_ANIME: ("h265", "anime"),
        SET_KEY_PATH_FILME: ("h265", "film"),
    }
    codec, media_type = key_map.get(settings_key, ("h265", "film"))
    return str(default_target_path(codec, media_type, root, create=create))


def ensure_default_storage_dirs(root: str | os.PathLike[str] | None = None) -> dict[str, dict[str, Path]]:
    """Legt alle Standard-Ausgabeordner an und gibt sie strukturiert zurück."""
    return {
        codec: {
            media_type: default_target_path(codec, media_type, root, create=True)
            for media_type in ("tv", "anime", "film")
        }
        for codec in ("h264", "h265", "av1")
    }
