# -*- coding: utf-8 -*-
"""Darstellungs-/Formatierungslogik für die Mediathek-GUI."""
from __future__ import annotations

from typing import Any


class MediaLibraryDialogPresenter:
    @staticmethod
    def format_stats(stats: Any) -> str:
        return (
            "Status: "
            f"{stats.media_count} Einträge ({stats.active_count} aktiv, {stats.inactive_count} inaktiv), "
            f"{stats.stream_count} Streams | "
            f"Filme: {stats.movie_count}, Serien: {stats.series_count}, Episoden: {stats.episode_count}\n"
            f"Schema: {stats.schema_version} | Aktualisiert: {stats.updated_at or 'unbekannt'}\n"
            f"Pfad: {stats.db_path}"
        )

    @staticmethod
    def search_row_values(row: dict[str, Any], preset: str) -> list[Any]:
        image = ""
        if row.get("width") or row.get("height"):
            image = f"{row.get('width') or '?'}x{row.get('height') or '?'}"

        flags: list[str] = []
        if row.get("has_dolby_vision"):
            flags.append("DV")
        if row.get("has_hdr10plus"):
            flags.append("HDR10+")
        elif row.get("is_hdr"):
            flags.append("HDR")
        elif preset == "sdr":
            flags.append("SDR")

        video = str(row.get("video_codec") or "")
        if flags:
            video = f"{video} ({', '.join(flags)})".strip()

        return [
            row.get("item_type"),
            row.get("title"),
            row.get("series_title"),
            row.get("season"),
            row.get("episode"),
            row.get("year"),
            video,
            image,
            row.get("audio_summary"),
            row.get("subtitle_summary"),
            row.get("deviation_reason"),
            row.get("path"),
        ]

    @staticmethod
    def format_import_result(result: Any) -> str:
        details = (
            "Import abgeschlossen.\n\n"
            f"Einträge: {result.imported_items}\n"
            f"Streams: {result.imported_streams}\n"
            f"Übersprungen: {result.skipped_items}"
        )
        warnings = list(getattr(result, "warnings", ()) or ())
        if warnings:
            details += "\n\nHinweise:\n- " + "\n- ".join(warnings[:10])
            if len(warnings) > 10:
                details += f"\n- ... {len(warnings) - 10} weitere Hinweise"
        return details

    @staticmethod
    def format_scan_result(result: Any) -> str:
        details = (
            "Scan abgeschlossen.\n\n"
            f"Gefundene Videodateien: {getattr(result, 'scanned_files', 0)}\n"
            f"Importierte Einträge: {getattr(result, 'imported_items', 0)}\n"
            f"Streams: {getattr(result, 'imported_streams', 0)}\n"
            f"Fehlerhafte Dateien: {getattr(result, 'failed_files', 0)}\n"
            f"Nicht erreichbare Ordner: {getattr(result, 'skipped_roots', 0)}"
        )
        warnings = list(getattr(result, "warnings", ()) or ())
        if warnings:
            details += "\n\nHinweise:\n- " + "\n- ".join(warnings[:12])
            if len(warnings) > 12:
                details += f"\n- ... {len(warnings) - 12} weitere Hinweise"
        return details
