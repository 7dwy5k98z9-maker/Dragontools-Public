# -*- coding: utf-8 -*-
from __future__ import annotations
import os
from PyQt6.QtWidgets import QFileDialog
from .drop_path_extractor import (
    _debug_mime_data, _extract_dropped_local_path, _extract_paths_from_mime_data, _iter_video_files_in_folder,
    _log_drop_rejection, _log_long_path_dragdrop_warning, _warn_non_video_file,
)
from ..core.paths import display_name, is_video_file, normalize_user_path, strip_long_path_prefix, to_long_path, VIDEO_EXTENSIONS

VIDEO_FILE_DIALOG_PATTERNS = " ".join(f"*{ext}" for ext in sorted(VIDEO_EXTENSIONS))

class ConvertWidgetQueueAddMixin:
    def collect_video_paths_from_mime_data(self, mime) -> list[str]:
        _debug_mime_data(self.log, "ConvertWidgetFileQueueHelper.collect_video_paths_from_mime_data", mime)
        paths = _extract_paths_from_mime_data(mime, log_fn=self.log)
        if not paths:
            visible = mime.text().strip() if mime.hasText() else "<leer>"
            _log_long_path_dragdrop_warning(self.log, mime)
            _log_drop_rejection(self.log, mime, visible)
            return []

        added: list[str] = []
        for p in paths:
            if os.path.isfile(to_long_path(p)):
                if not is_video_file(p):
                    _warn_non_video_file(self.log, p)
                    continue
                if self.file_list.add_path(p):
                    added.append(p)
            elif os.path.isdir(to_long_path(p)):
                folder_paths, ignored_count = _iter_video_files_in_folder(p)
                for path in folder_paths:
                    if self.file_list.add_path(path):
                        added.append(path)
                if ignored_count:
                    self.log("Nicht-Videodateien wurden ignoriert.", "warn")
            else:
                visible = strip_long_path_prefix(p)
                _log_drop_rejection(self.log, mime, visible)
        return added

    def collect_video_paths_from_urls(self, urls) -> list[str]:
        added: list[str] = []

        for url in urls:
            p = _extract_dropped_local_path(url, log_fn=self.log)
            if not p:
                raw_url = url.toString()
                visible = raw_url or "<leer>"
                self.log(
                    f"Drag&Drop-Pfad konnte nicht übernommen werden (Länge {len(visible)}): {visible}",
                    "warn",
                )
                continue

            if os.path.isfile(to_long_path(p)):
                if not is_video_file(p):
                    _warn_non_video_file(self.log, p)
                    continue
                if self.file_list.add_path(p):
                    added.append(p)
            elif os.path.isdir(to_long_path(p)):
                folder_paths, ignored_count = _iter_video_files_in_folder(p)
                for path in folder_paths:
                    if self.file_list.add_path(path):
                        added.append(path)
                if ignored_count:
                    self.log("Nicht-Videodateien wurden ignoriert.", "warn")
            else:
                visible = strip_long_path_prefix(p)
                self.log(
                    f"Drag&Drop-Pfad konnte nicht übernommen werden "
                    f"(Länge {len(visible)}): {visible}",
                    "warn",
                )

        return added

    def on_files_dropped(self, paths: list[str]) -> None:
        if not paths:
            return
        if not self.guard_queue_edit_allowed("Dateien hinzufügen"):
            return

        state = self.state
        thread = state.thread
        if not (thread and hasattr(thread, "add_file")):
            self._refresh_labels(paths)
            self._sync_total_files()
            return

        accepted: list[str] = []
        rejected: list[str] = []
        for path in paths:
            try:
                ok = thread.add_file(path)
                if ok is not False:
                    self.log(f"➕ Zur Queue hinzugefügt: {display_name(path)}", "info")
                    accepted.append(path)
                else:
                    rejected.append(path)
            except Exception as exc:
                self.log(
                    f"Live-Hinzufuegen fehlgeschlagen: {display_name(path)} - {exc}",
                    "warn",
                )
                self.log(
                    f"Betroffener Pfad (Laenge {len(strip_long_path_prefix(path))}): "
                    f"{strip_long_path_prefix(path)}",
                    "warn",
                )
                rejected.append(path)

        self._remove_rejected_from_gui(rejected)
        self.sync_queue_order()
        if accepted:
            self._refresh_labels(accepted)
            self.maybe_preflight_new_files(accepted)

        self._sync_total_files()

    def add_files(self) -> None:
        if not self.guard_queue_edit_allowed("Dateien hinzufügen"):
            return
        files, _ = QFileDialog.getOpenFileNames(
            self.parent_widget,
            "Videos",
            "",
            f"Videodateien ({VIDEO_FILE_DIALOG_PATTERNS});;Alle (*)",
        )

        added: list[str] = []
        for path in files:
            normalized = normalize_user_path(path)
            if not is_video_file(normalized):
                _warn_non_video_file(self.log, normalized or path)
                continue
            if self.file_list.add_path(normalized):
                added.append(normalized)
            else:
                visible = strip_long_path_prefix(normalized or path)
                self.log(
                    f"Datei nicht zur Queue übernommen "
                    f"(Laenge {len(visible)}): {visible}",
                    "warn",
                )

        state = self.state
        thread = state.thread
        if thread and hasattr(thread, "add_file"):
            rejected: list[str] = []
            for path in added:
                try:
                    ok = thread.add_file(path)
                    if ok is False:
                        rejected.append(path)
                except Exception as exc:
                    self.log(
                        f"Live-Hinzufuegen fehlgeschlagen: {display_name(path)} - {exc}",
                        "warn",
                    )
                    self.log(
                        f"Betroffener Pfad (Laenge {len(strip_long_path_prefix(path))}): "
                        f"{strip_long_path_prefix(path)}",
                        "warn",
                    )
                    rejected.append(path)
            self._remove_rejected_from_gui(rejected)
            added = [p for p in added if p not in rejected]
            self.sync_queue_order()
        if added:
            self._refresh_labels(added)
            self.maybe_preflight_new_files(added)

        self._sync_total_files()

    def add_folder(self) -> None:
        if not self.guard_queue_edit_allowed("Ordner hinzufügen"):
            return
        folder = QFileDialog.getExistingDirectory(self.parent_widget, "Ordner wählen")
        if not folder:
            return

        added: list[str] = []
        normalized_folder = normalize_user_path(folder)
        folder_paths, ignored_count = _iter_video_files_in_folder(normalized_folder)
        for path in folder_paths:
            if self.file_list.add_path(path):
                added.append(path)
        if ignored_count:
            self.log("Nicht-Videodateien wurden ignoriert.", "warn")

        state = self.state
        thread = state.thread
        if thread and hasattr(thread, "add_file"):
            rejected: list[str] = []
            for path in added:
                try:
                    ok = thread.add_file(path)
                    if ok is False:
                        rejected.append(path)
                except Exception as exc:
                    self.log(
                        f"Live-Hinzufuegen fehlgeschlagen: {display_name(path)} - {exc}",
                        "warn",
                    )
                    self.log(
                        f"Betroffener Pfad (Laenge {len(strip_long_path_prefix(path))}): "
                        f"{strip_long_path_prefix(path)}",
                        "warn",
                    )
                    rejected.append(path)
            self._remove_rejected_from_gui(rejected)
            added = [p for p in added if p not in rejected]
            self.sync_queue_order()
        if added:
            self._refresh_labels(added)
            self.maybe_preflight_new_files(added)

        self._sync_total_files()
