# -*- coding: utf-8 -*-
"""Darstellungs-/Formatierungslogik für die Mediathek-GUI."""
from __future__ import annotations

from typing import Any


class MediaLibraryDialogPresenter:
    @staticmethod
    def format_duration(duration_s: Any) -> str:
        try:
            seconds = float(duration_s)
        except (TypeError, ValueError):
            return ""
        if seconds <= 0:
            return ""
        rounded = int(round(seconds))
        hours, remainder = divmod(rounded, 3600)
        minutes, secs = divmod(remainder, 60)
        return f"{hours}:{minutes:02d}:{secs:02d}"

    @staticmethod
    def format_size(size_bytes: Any) -> str:
        try:
            value = int(size_bytes)
        except (TypeError, ValueError):
            return ""
        if value <= 0:
            return ""
        units = ("B", "KiB", "MiB", "GiB", "TiB")
        size = float(value)
        unit = units[0]
        for candidate in units:
            unit = candidate
            if size < 1024.0 or candidate == units[-1]:
                break
            size /= 1024.0
        if unit in {"B", "KiB"}:
            return f"{size:.0f} {unit}"
        return f"{size:.2f} {unit}"

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
            row.get("nfo_status"),
            row.get("nfo_issue_level"),
            MediaLibraryDialogPresenter.format_duration(row.get("duration_s")),
            MediaLibraryDialogPresenter.format_size(row.get("size_bytes")),
            row.get("deviation_reason"),
            row.get("path"),
        ]

    @staticmethod
    def format_nfo_scan_result(result: Any) -> str:
        details = (
            "NFO-Prüfung abgeschlossen.\n\n"
            f"Kandidaten: {getattr(result, 'candidates', 0)}\n"
            f"Geprüft: {getattr(result, 'scanned_items', 0)}\n"
            f"NFO vorhanden: {getattr(result, 'nfo_present', 0)}\n"
            f"NFO fehlt: {getattr(result, 'nfo_missing', 0)}\n"
            f"Speicherpfad nicht erreichbar: {getattr(result, 'nfo_unreachable', 0)}\n"
            f"NFO ungültig/nicht lesbar: {getattr(result, 'nfo_invalid', 0)}\n"
            f"Gefundene Abweichungen: {getattr(result, 'issues', 0)}"
        )
        warnings = list(getattr(result, "warnings", ()) or ())
        if warnings:
            details += "\n\nHinweise:\n- " + "\n- ".join(warnings[:12])
            if len(warnings) > 12:
                details += f"\n- ... {len(warnings) - 12} weitere Hinweise"
        return details

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
