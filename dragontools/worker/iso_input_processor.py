from __future__ import annotations

from pathlib import Path

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
        explicit = list(host.selected_titles.get(path) or host.selected_titles.get(str(src.resolve())) or [])
        if explicit:
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
        if host.ffmpeg_fallback:
            host.log_message("⚠️ MakeMKV-Extraktion fehlgeschlagen. FFmpeg-Fallback wird einmalig versucht.", "warn")
            if host.extract_with_ffmpeg_fallback(path, output_dir):
                host.file_progress.emit(path, 100, None)
                host.file_result.emit(path, True, "Extraktion über FFmpeg-Fallback abgeschlossen")
                return False
        host.file_result.emit(path, False, "Extraktion fehlgeschlagen")
        return False

    def _fail(self, path: str, message: str) -> None:
        self._host.log_message(f"⚠️ {message}")
        self._host.file_result.emit(path, False, message)
