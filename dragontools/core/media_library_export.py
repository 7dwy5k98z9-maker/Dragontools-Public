from __future__ import annotations

import csv
from contextlib import closing
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .media_library_db import _connect, _snapshot_database
from .media_library_search import search_library

def export_database(db_path: str | Path, output_dir: str | Path) -> Path:
    db = Path(db_path)
    if not db.exists():
        raise FileNotFoundError(f"Mediathek-Datenbank nicht gefunden: {db}")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    target = out_dir / f"{db.stem}_export_{stamp}{db.suffix}"
    return _snapshot_database(db, target)


def export_database_to_csv(db_path: str | Path, output_dir: str | Path) -> list[Path]:
    db = Path(db_path)
    if not db.exists():
        raise FileNotFoundError(f"Mediathek-Datenbank nicht gefunden: {db}")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    targets: list[Path] = []
    overview_target = out_dir / f"{db.stem}_medien_uebersicht_{stamp}.csv"
    export_media_overview_to_csv(db, overview_target)
    targets.append(overview_target)
    with closing(_connect(db)) as conn:
        for table in ("media_items", "media_streams", "path_mappings", "meta"):
            cur = conn.execute(f"SELECT * FROM {table}")
            columns = [desc[0] for desc in cur.description or []]
            rows = cur.fetchall()
            target = out_dir / f"{db.stem}_{table}_{stamp}.csv"
            with target.open("w", encoding="utf-8-sig", newline="") as fh:
                writer = csv.writer(fh, delimiter=";")
                writer.writerow(columns)
                for row in rows:
                    writer.writerow([row[column] for column in columns])
            targets.append(target)
    return targets


def export_media_overview_to_csv(db_path: str | Path, output_file: str | Path) -> Path:
    rows = search_library(db_path, "all", "", limit=1_000_000, media_type="videos")
    return export_search_results_to_csv(rows, output_file)


def export_search_results_to_csv(rows: Iterable[dict[str, Any]], output_file: str | Path) -> Path:
    target = Path(output_file)
    target.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        ("area", "Bereich"),
        ("item_type", "Typ"),
        ("title", "Titel"),
        ("series_title", "Serie"),
        ("season", "Staffel"),
        ("episode", "Episode"),
        ("year", "Jahr"),
        ("container", "Container"),
        ("duration_s", "Dauer (Sekunden)"),
        ("size_bytes", "Dateigröße (Bytes)"),
        ("video_codec", "Video"),
        ("video_profile", "Videoprofil"),
        ("video_bitrate", "Video-Bitrate"),
        ("overall_bitrate", "Gesamtbitrate"),
        ("frame_rate", "Framerate"),
        ("frame_rate_mode", "Framerate-Modus"),
        ("frame_count", "Frameanzahl"),
        ("pix_fmt", "Pixelformat"),
        ("bit_depth", "Bittiefe"),
        ("color_space", "Farbraum"),
        ("color_transfer", "Transfercharakteristik"),
        ("color_primaries", "Farbprimärfarben"),
        ("width", "Breite"),
        ("height", "Höhe"),
        ("image_summary", "Bild"),
        ("dynamic_range", "Dynamikumfang"),
        ("audio_summary", "Audio"),
        ("subtitle_summary", "Untertitel"),
        ("deviation_reason", "Abweichung"),
        ("analysis_status", "Analyse"),
        ("path", "Pfad"),
    ]

    def cell(row: dict[str, Any], key: str) -> Any:
        if key == "image_summary":
            width = row.get("width")
            height = row.get("height")
            return f"{width}x{height}" if width and height else ""
        if key == "dynamic_range":
            if row.get("has_dolby_vision"):
                return "Dolby Vision"
            if row.get("has_hdr10plus"):
                return "HDR10+"
            if row.get("is_hdr"):
                return "HDR"
            video_range = str(row.get("video_range") or "").casefold()
            if any(marker in video_range for marker in ("sdr", "bt709", "bt.709", "rec709", "rec.709")):
                return "SDR"
            return "unbekannt"
        return row.get(key)

    with target.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.writer(fh, delimiter=";")
        writer.writerow([label for _key, label in columns])
        for row in rows:
            writer.writerow(["" if cell(row, key) is None else cell(row, key) for key, _label in columns])
    return target
