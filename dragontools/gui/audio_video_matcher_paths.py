# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import QFileDialog, QMessageBox

from ..core.paths import VIDEO_EXTENSIONS, app_documents_dir


def default_matcher_output_path(target_text: str) -> Path | None:
    target = Path(str(target_text or "").strip())
    if not target.name:
        return None
    return app_documents_dir() / "AudioVideoMatcher" / f"{target.stem}_DE-Sync.mkv"


class AudioVideoMatcherPathsMixin:
    """Owns file dialogs, output naming and path validation."""

    def _choose_video(self, line, title: str) -> None:
        files_filter = (
            f"Video-Dateien ({' '.join('*' + ext for ext in sorted(VIDEO_EXTENSIONS))});;"
            "Alle Dateien (*)"
        )
        path, _ = QFileDialog.getOpenFileName(self, title, "", files_filter)
        if path:
            line.setText(path)

    def _choose_output(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Ausgabe-MKV wählen",
            self.output_edit.text().strip(),
            "Matroska Video (*.mkv);;Alle Dateien (*)",
        )
        if path:
            if not Path(path).suffix:
                path += ".mkv"
            self.output_edit.setText(path)

    def _maybe_update_output_name(self) -> None:
        current = Path(self.output_edit.text().strip())
        if current.name not in {"", "synchronisiert.mkv"}:
            return
        target = default_matcher_output_path(self.target_edit.text())
        if target is not None:
            self.output_edit.setText(str(target))

    def _validate_paths(self, *, require_output: bool) -> bool:
        source = Path(self.source_edit.text().strip())
        target = Path(self.target_edit.text().strip())
        if not source.exists():
            QMessageBox.information(self, "Audio-Video-Matcher", "Bitte die deutsche Quelle wählen.")
            return False
        if not target.exists():
            QMessageBox.information(self, "Audio-Video-Matcher", "Bitte das Zielvideo wählen.")
            return False
        if require_output and not self.output_edit.text().strip():
            QMessageBox.information(self, "Audio-Video-Matcher", "Bitte einen Ausgabepfad wählen.")
            return False
        return True
