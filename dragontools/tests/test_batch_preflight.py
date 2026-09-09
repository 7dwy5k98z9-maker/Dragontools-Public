from __future__ import annotations

from datetime import datetime

from dragontools.core.batch_preflight import (
    build_batch_preflight_rows,
    format_batch_preflight_report,
    split_problem_rows,
)


def _base_preview(**updates):
    preview = {
        "video": {
            "available": True,
            "codec": "hevc",
            "width": 3840,
            "height": 2160,
            "bit_depth": 10,
            "is_hdr": False,
            "has_dv": False,
            "dv_profile": None,
            "has_hdr10plus": False,
        },
        "source_codec": "hevc",
        "analysis_source": "fake",
        "analysis_warnings": [],
        "pipeline": "standard",
        "target_container": "mkv",
        "dv_preserved": False,
        "hdr10plus_preserved": False,
        "ignored_hdr": [],
        "archive_reason": None,
        "audio": {
            "source_count": 1,
            "selection_count": 1,
            "selected_streams": [
                {
                    "index": 1,
                    "language": "de",
                    "source_codec": "dts",
                    "source_channels": 6,
                    "decision": "transcode",
                    "target_codec": "eac3",
                    "target_channels": 6,
                    "target_bitrate": 640,
                    "is_extra_stereo": False,
                }
            ],
        },
        "subtitles": {
            "source_count": 1,
            "burn_in": False,
            "container_copy_supported": True,
            "copy_candidate_count": 1,
            "burn_blocked_reason": None,
        },
        "move": {
            "planned_target": None,
            "available": False,
            "status": "not_present",
        },
        "overrides": {},
    }
    preview.update(updates)
    return preview


def test_batch_preflight_marks_clean_file_as_ok():
    def fake_preview(path, **kwargs):
        return _base_preview(
            video={**_base_preview()["video"], "has_dv": True, "dv_profile": "7"},
            pipeline="dv",
            target_container="mp4",
            dv_preserved=True,
            move={"planned_target": r"D:\Filme", "available": True, "status": "planned"},
        )

    rows = build_batch_preflight_rows([r"C:\in\film.mkv"], preview_builder=fake_preview)

    assert rows[0]["severity"] == "ok"
    assert rows[0]["problem"] is False
    assert "DV P7 erhalten" in rows[0]["hdr"]
    assert ".mp4" in rows[0]["target"]
    assert r"D:\Filme" in rows[0]["target"]


def test_batch_preflight_warns_for_ignored_dv_and_old_container():
    def fake_preview(path, **kwargs):
        return _base_preview(
            video={**_base_preview()["video"], "codec": "h264", "has_dv": True},
            source_codec="h264",
            ignored_hdr=["dv"],
            archive_reason="Quelldatei wird archiviert.",
        )

    rows = build_batch_preflight_rows([r"C:\in\film.avi"], preview_builder=fake_preview)
    ok_rows, problem_rows = split_problem_rows(rows)

    assert ok_rows == []
    assert len(problem_rows) == 1
    assert rows[0]["severity"] == "warn"
    assert any("Dolby Vision" in warning for warning in rows[0]["warnings"])
    assert any(".avi" in warning for warning in rows[0]["warnings"])


def test_batch_preflight_turns_analysis_exception_into_error_row():
    def fake_preview(path, **kwargs):
        raise RuntimeError("ffprobe fehlt")

    rows = build_batch_preflight_rows([r"C:\in\kaputt.mkv"], preview_builder=fake_preview)

    assert rows[0]["severity"] == "error"
    assert rows[0]["problem"] is True
    assert "ffprobe fehlt" in rows[0]["warnings"][0]


def test_batch_preflight_errors_when_no_video_stream_is_detected():
    def fake_preview(path, **kwargs):
        return _base_preview(video={"available": False})

    rows = build_batch_preflight_rows([r"C:\in\audio_only.mkv"], preview_builder=fake_preview)

    assert rows[0]["severity"] == "error"
    assert any("Kein Videostream" in warning for warning in rows[0]["warnings"])


def test_batch_preflight_filesystem_checks_show_planned_output(tmp_path):
    src = tmp_path / "film.mkv"
    src.write_bytes(b"input")

    def fake_preview(path, **kwargs):
        return _base_preview()

    rows = build_batch_preflight_rows(
        [str(src)],
        codec="h265",
        preview_builder=fake_preview,
        filesystem_checks=True,
    )

    assert rows[0]["severity"] == "ok"
    assert "film_H265.mkv" in rows[0]["target"]
    assert rows[0]["filesystem"]["final_output_path"].endswith("film_H265.mkv")


def test_batch_preflight_detects_overwrite_container_conflict(tmp_path):
    src = tmp_path / "film.mkv"
    src.write_bytes(b"input")
    conflict = tmp_path / "film.mp4"
    conflict.write_bytes(b"already there")

    def fake_preview(path, **kwargs):
        return _base_preview(target_container="mp4")

    rows = build_batch_preflight_rows(
        [str(src)],
        codec="h265",
        preview_builder=fake_preview,
        overwrite_original=True,
        filesystem_checks=True,
    )

    assert rows[0]["severity"] == "error"
    assert any("Zieldatei existiert bereits" in warning for warning in rows[0]["warnings"])


def test_batch_preflight_detects_move_conflict_with_other_video_extension(tmp_path):
    src = tmp_path / "film.mkv"
    move_dir = tmp_path / "ziel"
    src.write_bytes(b"input")
    move_dir.mkdir()
    (move_dir / "film.mp4").write_bytes(b"already there")

    def fake_preview(path, **kwargs):
        return _base_preview(
            move={
                "planned_target": str(move_dir),
                "available": True,
                "status": "planned",
            }
        )

    rows = build_batch_preflight_rows(
        [str(src)],
        codec="h265",
        preview_builder=fake_preview,
        overwrite_original=True,
        filesystem_checks=True,
    )

    assert any("Verschiebe-Zielkonflikt vorhanden" in warning for warning in rows[0]["warnings"])
    assert any("film.mp4" in warning for warning in rows[0]["warnings"])


def test_batch_preflight_pipeline_summary_shows_encoder_profile():
    def fake_preview(path, **kwargs):
        return _base_preview(
            overrides={
                "encoder_profile": {
                    "key": "film_nvenc",
                    "label": "Film NVENC",
                }
            }
        )

    rows = build_batch_preflight_rows([r"C:\in\film.mkv"], preview_builder=fake_preview)

    assert "Profil: Film NVENC" in rows[0]["pipeline"]


def test_batch_preflight_pipeline_summary_shows_strip_only_override():
    def fake_preview(path, **kwargs):
        return _base_preview(overrides={"processing_mode": "strip_only"})

    rows = build_batch_preflight_rows([r"C:\in\film.mkv"], preview_builder=fake_preview)

    assert "Strip-Only" in rows[0]["pipeline"]
    assert any("Strip-Only" in reason for reason in rows[0]["decision_reasons"])


def test_batch_preflight_warns_for_strip_only_dv_mp4_and_burn_in():
    def fake_preview(path, **kwargs):
        return _base_preview(
            video={
                **_base_preview()["video"],
                "has_dv": True,
                "has_hdr10plus": True,
            },
            target_container="mp4",
            subtitles={
                "source_count": 2,
                "burn_in": True,
                "container_copy_supported": True,
                "copy_candidate_count": 1,
                "burn_blocked_reason": None,
            },
            overrides={"processing_mode": "strip_only"},
        )

    rows = build_batch_preflight_rows([r"C:\in\film.mkv"], preview_builder=fake_preview)
    warnings = "\n".join(rows[0]["warnings"])

    assert rows[0]["severity"] == "warn"
    assert "Dolby Vision" in warnings
    assert "HDR10+" in warnings
    assert "Strip-Only + MP4" in warnings
    assert "Burn-In ist nicht möglich" in warnings


def test_batch_preflight_explains_rule_decisions():
    def fake_preview(path, **kwargs):
        return _base_preview(
            subtitles={
                "source_count": 2,
                "override_mode": "auto",
                "burn_in": True,
                "burn_candidate": {
                    "index": 3,
                    "language": "de",
                    "codec": "subrip",
                    "forced": True,
                },
                "container_copy_supported": True,
                "stream_copy_candidates": [
                    {
                        "index": 4,
                        "language": "de",
                        "codec": "ass",
                        "forced": False,
                    }
                ],
                "copy_candidate_count": 1,
                "burn_blocked_reason": None,
            }
        )

    rows = build_batch_preflight_rows([r"C:\in\film.mkv"], preview_builder=fake_preview)
    reasons = "\n".join(rows[0]["decision_reasons"])

    assert "Pipeline: Standardpfad" in reasons
    assert "Audio #1" in reasons
    assert "Burn-in gewinnt" in reasons
    assert "Stream-Copy" in reasons


def test_batch_preflight_report_includes_decisions_and_warnings():
    rows = [{
        "status": "Warnung",
        "severity": "warn",
        "name": "film.mkv",
        "path": r"C:\in\film.mkv",
        "video": "HEVC | 3840x2160",
        "hdr": "HDR10",
        "audio": "1/2 Spur(en)",
        "subtitles": "1 Untertitel",
        "target": r"D:\Ziel\film.mkv",
        "pipeline": "STANDARD -> .mkv",
        "profile": "Standard",
        "analysis_source": "fake",
        "decision_reasons": ["Audio #1 gewinnt wegen Sprache de."],
        "warnings": ["Verschiebe-Zielkonflikt vorhanden."],
    }]

    text = format_batch_preflight_report(
        rows,
        created_at=datetime(2026, 8, 22, 10, 30, 0),
    )

    assert "Regel-/Profil-Simulator aktuelle Queue - Dragon Tools" in text
    assert "Dateien: 1 | OK: 0 | Warnungen: 1 | Fehler: 0" in text
    assert "Profil: Standard" in text
    assert "Audio #1 gewinnt wegen Sprache de." in text
    assert "Verschiebe-Zielkonflikt vorhanden." in text


def test_batch_preflight_pipeline_summary_shows_manual_encoder_override():
    def fake_preview(path, **kwargs):
        return _base_preview(
            overrides={
                "encoder_override": {
                    "codec": "h265",
                    "encoder": "nvenc",
                    "quality": 20,
                    "preset": "p6",
                    "scale_mode": "1080p",
                }
            }
        )

    rows = build_batch_preflight_rows([r"C:\in\film.mkv"], preview_builder=fake_preview)

    assert "Encoder: NVENC CQ 20 | 1080p" in rows[0]["pipeline"]
    assert rows[0]["profile"] == "Manueller Encoder (NVENC)"
    assert any("Encoder/Skalierung = NVENC, CQ 20, 1080p" in reason for reason in rows[0]["decision_reasons"])
