# -*- coding: utf-8 -*-
import os
from pathlib import Path

import pytest

from dragontools.core import paths


@pytest.mark.parametrize(
    ("subdir", "names"),
    [
        ("FFmpeg", ("ffprobe.exe", "ffprobe")),
        ("MKVToolNix", ("mkvmerge.exe", "mkvmerge")),
        ("MKVToolNix", ("mkvextract.exe", "mkvextract")),
        ("MakeMKV", ("makemkvcon64.exe", "makemkvcon.exe", "makemkvcon")),
        ("GPAC", ("MP4Box.exe", "mp4box.exe", "MP4Box", "mp4box")),
    ],
)
def test_find_tool_searches_third_party_product_dirs(tmp_path, monkeypatch, subdir, names):
    exe = tmp_path / "third_party" / subdir / names[0]
    exe.parent.mkdir(parents=True)
    exe.write_text("")

    monkeypatch.setattr(paths, "BASE", tmp_path)
    monkeypatch.setattr(paths, "EXE_DIR", tmp_path)
    monkeypatch.setenv("PATH", "")

    found = paths.find_tool(*names)
    assert Path(found).resolve() == exe.resolve()


def test_extend_path_adds_third_party_product_dirs(tmp_path, monkeypatch):
    ffmpeg_dir = tmp_path / "third_party" / "FFmpeg"
    mkv_dir = tmp_path / "third_party" / "MKVToolNix"
    ffmpeg_dir.mkdir(parents=True)
    mkv_dir.mkdir(parents=True)

    monkeypatch.setattr(paths, "BASE", tmp_path)
    monkeypatch.setattr(paths, "EXE_DIR", tmp_path)
    monkeypatch.setenv("PATH", "")

    paths.extend_path()
    entries = {Path(p).resolve() for p in os.environ["PATH"].split(os.pathsep) if p}

    assert ffmpeg_dir.resolve() in entries
    assert mkv_dir.resolve() in entries


def test_find_tool_searches_pyinstaller_contents_programme_dirs(tmp_path, monkeypatch):
    exe = tmp_path / "Daten" / "Programme" / "MakeMKV" / "makemkvcon64.exe"
    exe.parent.mkdir(parents=True)
    exe.write_text("")

    monkeypatch.setattr(paths, "BASE", tmp_path / "Daten")
    monkeypatch.setattr(paths, "EXE_DIR", tmp_path)
    monkeypatch.setenv("PATH", "")

    found = paths.find_tool("makemkvcon64.exe", "makemkvcon.exe", "makemkvcon")
    assert Path(found).resolve() == exe.resolve()


def test_extend_path_adds_pyinstaller_contents_programme_dirs(tmp_path, monkeypatch):
    makemkv_dir = tmp_path / "Daten" / "Programme" / "MakeMKV"
    makemkv_dir.mkdir(parents=True)

    monkeypatch.setattr(paths, "BASE", tmp_path / "Daten")
    monkeypatch.setattr(paths, "EXE_DIR", tmp_path)
    monkeypatch.setenv("PATH", "")

    paths.extend_path()
    entries = {Path(p).resolve() for p in os.environ["PATH"].split(os.pathsep) if p}

    assert makemkv_dir.resolve() in entries


def test_default_storage_dirs_are_created(tmp_path):
    created = paths.ensure_default_storage_dirs(tmp_path)

    for codec, codec_dir in (("h264", "H264"), ("h265", "H265"), ("av1", "AV1")):
        for media_type, media_dir in (("tv", "TV"), ("anime", "Anime"), ("film", "Filme")):
            expected = tmp_path / "Ausgabe" / codec_dir / media_dir
            assert created[codec][media_type] == expected.resolve()
            assert expected.is_dir()


def test_default_target_path_for_settings_key_maps_codec_and_media_type(tmp_path):
    from dragontools.core.settings import SET_KEY_PATH_H265_ANIME

    expected = tmp_path / "Ausgabe" / "H265" / "Anime"

    result = paths.default_target_path_for_settings_key(SET_KEY_PATH_H265_ANIME, tmp_path)

    assert Path(result) == expected.resolve()
    assert expected.is_dir()


def test_default_target_paths_can_be_returned_without_creating_dirs(tmp_path):
    result = paths.default_target_paths("av1", tmp_path, create=False)

    assert result["tv"] == str((tmp_path / "Ausgabe" / "AV1" / "TV").resolve())
    assert not (tmp_path / "Ausgabe").exists()
