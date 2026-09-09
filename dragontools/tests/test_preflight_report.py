from __future__ import annotations

from datetime import datetime

from dragontools.core.preflight_report import build_preflight_report, write_preflight_report


def test_preflight_report_includes_targets_rules_and_warnings():
    src = r"C:\Eingang\Meine Serie - S01E02.mkv"
    rows = [
        {
            "path": src,
            "severity": "warn",
            "status": "Warnung",
            "video": "AVC | 1920x1080 | 8-bit",
            "hdr": "SDR",
            "audio": "Audio 1 (de, aac) wird kopiert",
            "subtitles": "1 Untertitel wird kopiert",
            "pipeline": "STANDARD -> .mkv",
            "target": r"C:\Ausgabe\Meine Serie\Staffel 01",
            "warnings": ["Verschiebe-Zielkonflikt vorhanden."],
        }
    ]

    text = build_preflight_report(
        [src],
        planned_targets={src: r"C:\Ausgabe\Meine Serie\Staffel 01"},
        target_paths={"anime": r"C:\Ausgabe", "tv": None, "film": r"D:\Filme"},
        rows=rows,
        settings_summary={"Codec": "H.265", "Original ersetzen": "ja"},
        created_at=datetime(2026, 8, 22, 12, 30, 5),
    )

    assert "Preflight-Bericht" in text
    assert "22.08.2026 12:30:05 Uhr" in text
    assert "Warnung 1" in text
    assert "Meine Serie - S01E02.mkv" in text
    assert "Serie: Meine Serie | Staffel 01 | Folge 02" in text
    assert r"C:\Ausgabe\Meine Serie\Staffel 01" in text
    assert "Verschiebe-Zielkonflikt vorhanden." in text
    assert "Codec: H.265" in text


def test_preflight_report_shows_film_series_subpath():
    src = r"C:\Eingang\Film.mkv"

    text = build_preflight_report(
        [src],
        planned_targets={
            src: {
                "target": r"D:\Filme\Filmreihe\Film",
                "subpath": r"Trilogie\Teil 1",
            }
        },
        target_paths={"film": r"D:\Filme"},
        created_at=datetime(2026, 8, 22, 13, 0, 0),
    )

    assert "Film/Einzeldatei" in text
    assert r"D:\Filme\Filmreihe\Film" in text
    assert r"Unterordner: Trilogie\Teil 1" in text
    assert "Regelvorschau: nicht erstellt" in text


def test_write_preflight_report_creates_file(tmp_path):
    src = r"C:\Eingang\Film.mkv"

    path = write_preflight_report(
        [src],
        planned_targets={src: r"D:\Filme\Film"},
        report_dir=tmp_path,
        created_at=datetime(2026, 8, 22, 14, 0, 0),
    )

    assert path.name == "20260822_140000_Preflight.txt"
    assert path.read_text(encoding="utf-8").startswith("📋 Preflight-Bericht")
