from __future__ import annotations

from types import SimpleNamespace

from dragontools.gui import media_info_text_builder as builder


def _media_info():
    video = SimpleNamespace(
        width=3840,
        height=1600,
        codec="hevc",
        pix_fmt="yuv420p10le",
        duration_s=65.5,
        frame_count=1572,
        frame_rate="24000/1001",
        frame_rate_mode="CFR",
        bit_depth=10,
        color_space="bt2020nc",
        color_transfer="smpte2084",
        color_primaries="bt2020",
    )
    return SimpleNamespace(
        primary_video=video,
        audio_streams=[SimpleNamespace(language="deu", codec="eac3", channels=6, bitrate=640000, title="Deutsch")],
        subtitle_streams=[SimpleNamespace(language="de", codec="subrip", forced=True, title="Forced")],
        analysis_source="ffprobe + MediaInfo",
        color_range="limited",
        is_hdr=True,
        has_hdr10plus=True,
        has_dv=True,
        dolby_vision_profile=8,
        dv_codec_tag="dvhe.08.06",
    )


def test_build_media_info_text_preserves_all_sections(monkeypatch):
    monkeypatch.setattr(
        builder,
        "_build_rules_preview",
        lambda *_args, **_kwargs: {
            "pipeline": "DV8",
            "target_container": "mkv",
            "target_video": {"resolution": "3840x1600", "autocrop_pending": False},
            "dv_preserved": True,
            "hdr10plus_preserved": True,
            "audio": {
                "override_action": "auto",
                "selected_streams": [{
                    "index": 1,
                    "language": "deu",
                    "source_codec": "eac3",
                    "target_codec": "eac3",
                    "source_channels": 6,
                    "target_channels": 6,
                    "decision": "copy",
                    "target_bitrate": 640000,
                }],
            },
            "subtitles": {
                "override_mode": "auto",
                "burn_candidate": {"index": 2, "language": "de", "codec": "subrip", "forced": True},
                "container_copy_supported": True,
                "stream_copy_candidates": [{"index": 2, "language": "de", "codec": "subrip", "forced": True}],
            },
            "overrides": {
                "processing_mode": "strip_only",
                "imax": True,
                "_legacy": {"audio_action": "copy", "burn_mode": "forced", "burn_stream_index": 2},
            },
            "move": {"available": True, "planned_target": r"D:\\Filme"},
        },
    )

    text = builder.build_media_info_text(
        "film.mkv",
        mi=_media_info(),
        file_override={},
        planned_target=r"D:\\Filme",
        subtitle_rules={},
        codec="h265",
    )

    assert "Auflösung:      3840×1600" in text
    assert "Dolby Vision:   Ja (Profil 8 / dvhe.08.06)" in text
    assert "Audio 1: Deutsch | eac3 | 5.1 | 640 kbps | Titel: Deutsch" in text
    assert "Untertitel 1: Deutsch | subrip | Forced: Ja | Titel: Forced" in text
    assert "Pipeline:       DV8" in text
    assert "Endauflösung:   3840x1600" in text
    assert "Verarbeitung:   Strip-Only" in text
    assert r"Zielordner:     D:\\Filme" in text


def test_build_media_info_text_keeps_analysis_when_rules_preview_fails(monkeypatch):
    def fail(*_args, **_kwargs):
        raise RuntimeError("preview kaputt")

    monkeypatch.setattr(builder, "_build_rules_preview", fail)
    text = builder.build_media_info_text(
        "film.mkv",
        mi=_media_info(),
        file_override={},
        planned_target=None,
        subtitle_rules={},
        codec="h265",
    )

    assert "========= Video =========" in text
    assert "========= Audio =========" in text
    assert "========= Untertitel =========" in text
    assert "Rules Preview konnte nicht erstellt werden." in text
    assert "Fehler: preview kaputt" in text
