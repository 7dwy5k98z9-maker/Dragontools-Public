# -*- coding: utf-8 -*-
from __future__ import annotations

import pytest

from dragontools.subtitle.converter import ass_to_txt, srt_to_txt, txt_to_ass, txt_to_srt


def test_srt_to_txt_preserves_timestamps_and_removes_numbers(tmp_path):
    srt = tmp_path / "Film.srt"
    srt.write_text(
        "1\r\n"
        "00:00:00,080 --> 00:00:02,760\r\n"
        "...\r\n"
        "\r\n"
        "2\r\n"
        "00:00:03,000 --> 00:00:05,480\r\n"
        "Musique douce\r\n",
        encoding="utf-8",
        newline="",
    )

    assert srt_to_txt(srt) == (
        "00:00:00,080 --> 00:00:02,760\n"
        "...\n\n"
        "00:00:03,000 --> 00:00:05,480\n"
        "Musique douce"
    )


def test_srt_to_txt_writes_timestamped_output_file(tmp_path):
    srt = tmp_path / "Film.srt"
    out = tmp_path / "Film.txt"
    srt.write_text(
        "7\n"
        "00:00:06,360 --> 00:00:07,400\n"
        "-Vous pouvez éviter\n"
        "\n",
        encoding="utf-8",
    )

    result = srt_to_txt(srt, out)

    assert result == "00:00:06,360 --> 00:00:07,400\n-Vous pouvez éviter"
    assert out.read_text(encoding="utf-8") == result


def test_txt_to_srt_recreates_numbered_blocks(tmp_path):
    txt = tmp_path / "Film.txt"
    txt.write_text(
        "00:00:00,080 --> 00:00:02,760\n"
        "...\n"
        "\n"
        "00:00:03,000 --> 00:00:05,480\n"
        "Sanfte Musik\n"
        "\n"
        "00:00:06,360 --> 00:00:07,400\n"
        "-Du kannst vermeiden\n"
        "dich zurückzuverwandeln.\n",
        encoding="utf-8",
    )

    assert txt_to_srt(txt) == (
        "1\n"
        "00:00:00,080 --> 00:00:02,760\n"
        "...\n\n"
        "2\n"
        "00:00:03,000 --> 00:00:05,480\n"
        "Sanfte Musik\n\n"
        "3\n"
        "00:00:06,360 --> 00:00:07,400\n"
        "-Du kannst vermeiden\n"
        "dich zurückzuverwandeln."
    )


def test_txt_to_srt_writes_output_file(tmp_path):
    txt = tmp_path / "Film.txt"
    out = tmp_path / "Film.srt"
    txt.write_text(
        "00:00:00,080 --> 00:00:02,760\n"
        "Hallo\n",
        encoding="utf-8",
    )

    result = txt_to_srt(txt, out)

    assert out.read_text(encoding="utf-8") == result
    assert result.startswith("1\n00:00:00,080 --> 00:00:02,760\nHallo")


def test_txt_to_ass_converts_timestamped_txt(tmp_path):
    txt = tmp_path / "Film.txt"
    txt.write_text(
        "00:00:06,360 --> 00:00:07,400\n"
        "-Du kannst vermeiden\n"
        "dich zurückzuverwandeln.\n",
        encoding="utf-8",
    )

    result = txt_to_ass(txt)

    assert "[Events]" in result
    assert (
        "Dialogue: 0,0:00:06.36,0:00:07.40,Default,,0,0,0,,"
        "-Du kannst vermeiden\\Ndich zurückzuverwandeln."
    ) in result


def test_txt_to_srt_rejects_txt_without_timestamps(tmp_path):
    txt = tmp_path / "Film.txt"
    txt.write_text("Nur Text ohne Zeitstempel\n", encoding="utf-8")

    with pytest.raises(ValueError, match="keine erkennbaren Zeitstempel"):
        txt_to_srt(txt)


def test_ass_to_txt_preserves_timestamps_for_roundtrip(tmp_path):
    ass = tmp_path / "Film.ass"
    ass.write_text(
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
        "Dialogue: 0,0:00:06.36,0:00:07.40,Default,,0,0,0,,"
        "{\\i1}-Du kannst vermeiden\\Ndich zurückzuverwandeln.\n",
        encoding="utf-8",
    )

    result = ass_to_txt(ass)

    assert result == (
        "00:00:06,360 --> 00:00:07,400\n"
        "-Du kannst vermeiden\n"
        "dich zurückzuverwandeln."
    )
