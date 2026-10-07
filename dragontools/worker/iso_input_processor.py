from __future__ import annotations

from pathlib import Path
from .iso_models import FFMPEG_FALLBACK_TITLE_ID


def explicit_iso_titles(host, path):
    selection = getattr(host, 'selected_titles', {})
    return list(selection.get(path) or selection.get(str(Path(path).resolve())) or [])

class ISOInputProcessor:
    """Qt-free per-input ISO/disc orchestration via a small public host contract."""

    def __init__(self, host) -> None:
        self._host = host

    def process(self, path: str, total: int) -> None:
        host = self._host
        src = Path(path)
        output_dir = host.output_dir or str(src.parent)
        iso_type = host.detect_iso_type(path)
        host.start_file_log(path, total, iso_type)
        host.file_progress.emit(path, 2, None)
        if iso_type == "unknown":
            self._fail(path, "Eingabe ist keine klar erkennbare DVD-/Blu-ray-Struktur. MakeMKV-Scan wird nicht gestartet.")
            return

        host.reset_scan_error()
        titles = host.scan_titles(path) if host.makemkv_available() else []
        host.file_progress.emit(path, 15, titles)
        if not titles:
            self._handle_no_makemkv_titles(path, output_dir)
            return
        if host.scan_only:
            host.file_result.emit(path, True, "Analyse abgeschlossen")
            return
        title_ids = self._select_titles(path, src, titles)
        if not title_ids:
            return
        host.file_progress.emit(path, 25, title_ids)
        if self._extract(path, title_ids, output_dir):
            host.file_progress.emit(path, 100, None)
            host.file_result.emit(path, True, "Extraktion abgeschlossen")

    def _handle_no_makemkv_titles(self, path: str, output_dir: str) -> None:
        host = self._host
        if not host.scan_only:
            explicit = explicit_iso_titles(host, path)
            if explicit and explicit != [FFMPEG_FALLBACK_TITLE_ID]:
                self._fail(path, "MakeMKV-Titelauswahl kann ohne gültigen Disc-Scan nicht auf FFmpeg abgebildet werden.")
                return
            if not explicit and not getattr(host, 'auto_main_title', True):
                self._fail(path, "Keine Fallback-Auswahl und keine automatische Titelauswahl aktiviert.")
                return
        fallback_titles = host.scan_ffmpeg_fallback_titles(path) if host.ffmpeg_fallback else []
        if fallback_titles:
            host.file_progress.emit(path, 15, fallback_titles)
            if host.scan_only:
                host.file_result.emit(path, True, "Analyse abgeschlossen (nur FFmpeg-Fallback möglich)")
                return
        if host.ffmpeg_fallback and not host.scan_only:
            host.log_message("⚠️ MakeMKV lieferte keine nutzbaren Titel. FFmpeg-Fallback startet ohne Titelmenü.", "warn")
            if host.extract_with_ffmpeg_fallback(path, output_dir):
                host.file_progress.emit(path, 100, None)
                host.file_result.emit(path, True, "Extraktion über FFmpeg-Fallback abgeschlossen")
            else:
                host.file_result.emit(path, False, host.last_ffmpeg_fallback_error or host.last_scan_error or "Keine extrahierbaren Titel gefunden.")
            return
        self._fail(path, host.last_scan_error or "Keine extrahierbaren Titel gefunden.")

    def _select_titles(self, path: str, src: Path, titles: list[dict]) -> list[int] | None:
        host = self._host
        explicit = explicit_iso_titles(host, path)
        if explicit:
            available_ids: set[int] = set()
            for title in titles:
                try:
                    if title.get("id") is not None:
                        available_ids.add(int(title.get("id")))
                except (TypeError, ValueError):
                    continue
            try:
                explicit_ids = [int(title_id) for title_id in explicit]
            except (TypeError, ValueError):
                self._fail(path, "Explizite Titelauswahl enthält eine ungültige Titel-ID.")
                return None
            invalid = [title_id for title_id in explicit_ids if title_id not in available_ids]
            if invalid:
                self._fail(
                    path,
                    "Explizite Titelauswahl ist nach dem aktuellen Disc-Scan nicht mehr gültig: "
                    + ", ".join(map(str, invalid)),
                )
                return None
            explicit = list(dict.fromkeys(explicit_ids))
            host.log_message(f"ℹ️ Verwende explizit ausgewählte Titel: {', '.join(map(str, explicit))}")
            return explicit
        if not host.auto_main_title:
            self._fail(path, "Keine Titel ausgewählt und kein automatischer Haupttitel-Vorschlag aktiv.")
            return None
        title_ids, series_disc = host.select_auto_titles(titles)
        if not title_ids:
            self._fail(path, "Es konnte kein Haupttitel vorgeschlagen werden.")
            return None
        host.log_message(
            f"ℹ️ Serien-Disc erkannt; Episoden-Titel: {', '.join(map(str, title_ids))}"
            if series_disc else f"ℹ️ Haupttitel-Vorschlag: {title_ids[0]}"
        )
        return title_ids

    def _extract(self, path: str, title_ids: list[int], output_dir: str) -> bool:
        host = self._host
        ok = host.extract_titles(path, title_ids, output_dir)
        if host.abort_requested:
            host.file_result.emit(path, False, "Abgebrochen")
            return False
        if ok:
            return True
        # Sobald MakeMKV verwertbare Titel geliefert und ein konkreter Titel
        # ausgewählt wurde, darf der rohe FFmpeg-Fallback nicht einspringen:
        # VOB-/M2TS-Dateien lassen sich nicht sicher auf die MakeMKV-Titel-ID
        # abbilden. Ein Fallback könnte daher unbemerkt den falschen Film bzw.
        # eine andere Episode extrahieren. Fallback bleibt ausschließlich für
        # den Fall ohne verwertbare MakeMKV-Titelliste erlaubt.
        host.log_message(
            "⚠️ MakeMKV-Extraktion eines ausgewählten Titels fehlgeschlagen; "
            "FFmpeg-Fallback wird aus Titelsicherheitsgründen nicht verwendet.",
            "warn",
        )
        host.file_result.emit(path, False, "Extraktion fehlgeschlagen")
        return False

    def _fail(self, path: str, message: str) -> None:
        self._host.log_message(f"⚠️ {message}")
        self._host.file_result.emit(path, False, message)
