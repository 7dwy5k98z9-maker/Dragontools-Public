from __future__ import annotations

from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QListWidgetItem

from ..core.formatting import format_binary_size
from ..worker.iso_selection import choose_auto_titles
from ..worker.iso_thread import ISOThread


def _safe_display_name(path: str) -> str:
    try:
        return Path(path).name
    except Exception:
        return path


def _fmt_duration(seconds: int) -> str:
    total = max(0, int(seconds or 0))
    h = total // 3600
    m = (total % 3600) // 60
    s = total % 60
    return f"{h:02d}:{m:02d}:{s:02d}"


def _fmt_size(value: int) -> str:
    return format_binary_size(value, decimals=1)


class ISOWidgetRuntimeMixin:
    """Owns ISO worker creation, signal handling and converter handoff."""

    def _worker_options(self) -> dict:
        return {
            "output_dir": self.output_edit.text().strip() if self.output_edit is not None else None,
            "auto_main_title": self.auto_main_title_cb.isChecked() if self.auto_main_title_cb is not None else True,
            "auto_series_disc": self.auto_series_disc_cb.isChecked() if self.auto_series_disc_cb is not None else True,
            "handoff_to_converter": self.handoff_cb.isChecked() if self.handoff_cb is not None else False,
            "ffmpeg_fallback": self.ffmpeg_fallback_cb.isChecked() if self.ffmpeg_fallback_cb is not None else True,
        }

    def _analyze(self) -> None:
        if self._worker is not None or self._scan_worker is not None:
            return
        path = self._current_input_path()
        if not path:
            self._append_log("⚠️ Keine ISO-/Disc-Eingabe zum Analysieren ausgewählt.")
            return
        if self.title_list is None:
            self._append_log("❌ ISO-Titelliste ist nicht initialisiert.")
            return
        self.title_list.clear()
        self._analyzed_input_path = path

        self._scan_worker = ISOThread(
            inputs=[path],
            selected_titles={},
            scan_only=True,
            **self._worker_options(),
        )
        self._scan_worker.log_line.connect(self._append_log)
        self._scan_worker.progress.connect(self._on_progress)
        self._scan_worker.file_progress.connect(self._on_scan_file_progress)
        self._scan_worker.file_result.connect(self._on_scan_file_result)
        self._scan_worker.finished.connect(self._on_scan_finished)

        self._append_log("")
        self._append_log(f"▶ Analysiere {_safe_display_name(path)} …")
        self._set_running(True)
        self._scan_worker.start()

    def _start(self) -> None:
        if self._worker is not None:
            return
        if self.input_list is None or self.input_list.count() == 0:
            self._append_log("⚠️ Keine Eingaben vorhanden.")
            return
        output_dir = self.output_edit.text().strip() if self.output_edit is not None else ""
        if not output_dir:
            self._append_log("⚠️ Kein Zielpfad gewählt.")
            return

        files = [self.input_list.item(i).text() for i in range(self.input_list.count())]
        if len(files) > 1 and self._analyzed_input_path:
            self._append_log(
                "ℹ️ Explizite Titelauswahl gilt aktuell nur für die zuletzt analysierte Quelle. "
                "Alle anderen Eingaben verwenden den Auto-Vorschlag des Workers."
            )
        options = self._worker_options()
        options["output_dir"] = output_dir
        self._worker = ISOThread(
            inputs=files,
            selected_titles=self._collect_selected_titles(),
            **options,
        )
        self._worker.log_line.connect(self._append_log)
        self._worker.progress.connect(self._on_progress)
        self._worker.file_progress.connect(self._on_file_progress)
        self._worker.file_result.connect(self._on_file_result)
        self._worker.files_extracted.connect(self._on_files_extracted)
        self._worker.finished.connect(self._on_finished)

        if self.progress_bar is not None:
            self.progress_bar.setValue(0)
        self._append_log("")
        self._append_log(f"▶ Starte ISO-Extraktion für {len(files)} Eingabe(n) …")
        self._set_running(True)
        self._worker.start()

    def iter_shutdown_workers(self) -> tuple:
        return tuple(worker for worker in (self._worker, self._scan_worker) if worker is not None)

    def _abort(self) -> None:
        if self._worker is not None:
            self._worker.request_abort()
            self._append_log("⚠️ Abbruch angefordert ...")
        elif self._scan_worker is not None:
            self._scan_worker.request_abort()
            self._append_log("⚠️ Analyse-Abbruch angefordert ...")

    def _on_progress(self, pct: int) -> None:
        if self.progress_bar is not None:
            self.progress_bar.setValue(pct)

    def _on_file_progress(self, path: str, pct: int, obj) -> None:
        if self.progress_bar is not None:
            self.progress_bar.setValue(pct)
        if isinstance(obj, list) and obj:
            if isinstance(obj[0], dict):
                self._append_log(f"ℹ️ {_safe_display_name(path)}: {len(obj)} Titel gescannt.")
            elif isinstance(obj[0], int):
                self._append_log(f"ℹ️ {_safe_display_name(path)}: Titel {', '.join(map(str, obj))} ausgewählt.")

    def _on_file_result(self, path: str, success: bool, message: str) -> None:
        icon = "✅" if success else "❌"
        self._append_log(f"{icon} {_safe_display_name(path)} → {message}")

    def _on_scan_file_progress(self, path: str, pct: int, obj) -> None:
        if self.progress_bar is not None:
            self.progress_bar.setValue(pct)
        if not (isinstance(obj, list) and obj and isinstance(obj[0], dict)):
            return
        if self.title_list is None:
            self._append_log("❌ ISO-Titelliste ist nicht initialisiert; Scan-Ergebnis wird verworfen.")
            return
        self.title_list.clear()
        suggested: set[int] = set()
        series_disc = False
        if self._scan_worker is not None and self.auto_main_title_cb is not None and self.auto_main_title_cb.isChecked():
            suggested_ids, series_disc = choose_auto_titles(
                obj,
                detect_series_disc=(
                    self.auto_series_disc_cb.isChecked()
                    if self.auto_series_disc_cb is not None
                    else True
                ),
            )
            suggested = set(suggested_ids)
        for title in obj:
            tid = int(title.get("id") or 0)
            duration = int(title.get("duration") or 0)
            size = int(title.get("size") or 0)
            name = str(title.get("name") or f"Title {tid}")
            prefix = "★ " if tid in suggested else ""
            text = f"{prefix}Titel {tid}: {name} | Dauer {_fmt_duration(duration)} | Größe {_fmt_size(size)}"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, tid)
            item.setData(Qt.ItemDataRole.UserRole + 1, path)
            self.title_list.addItem(item)
        if suggested:
            if series_disc:
                self._append_log(
                    f"ℹ️ Serien-Disc erkannt; Episoden-Titel sichtbar markiert: "
                    f"{', '.join(map(str, sorted(suggested)))}"
                )
            else:
                self._append_log(f"ℹ️ Haupttitel-Vorschlag sichtbar markiert: Titel {next(iter(suggested))}")

    def _on_scan_file_result(self, path: str, success: bool, message: str) -> None:
        icon = "✅" if success else "❌"
        self._append_log(f"{icon} {_safe_display_name(path)} → {message}")

    def _on_scan_finished(self) -> None:
        self._set_running(False)
        self._scan_worker = None
        self._append_log("")
        self._append_log("🏁 Analyse abgeschlossen.")

    def _on_files_extracted(self, paths: list[str]) -> None:
        self._extracted_files = list(paths)

    def _on_finished(self) -> None:
        self._set_running(False)
        self._worker = None
        self._append_log("")
        self._append_log("🏁 ISO-Verarbeitung abgeschlossen.")
        if self.handoff_cb is not None and self.handoff_cb.isChecked() and self._extracted_files:
            count = len(self._extracted_files)
            self._append_log(f"➡️ Übergebe {count} Datei(en) an den Konverter …")
            self.handoff_requested.emit(list(self._extracted_files))
        self._extracted_files = []
