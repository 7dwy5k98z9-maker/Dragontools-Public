# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QFileDialog,
    QComboBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..core.audio_video_matcher import (
    CutMatchResult,
    TimeMappingResult,
    format_seconds,
    preferred_german_audio_stream,
)
from ..core.paths import VIDEO_EXTENSIONS, app_documents_dir
from ..core.settings import APP_VERSION
from ..worker.audio_video_match_thread import AudioVideoMatchThread
from .info_button import InfoButton


class AudioVideoMatcherWidget(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._worker: AudioVideoMatchThread | None = None
        self._analysis: TimeMappingResult | None = None
        self._cut_results: list[CutMatchResult] = []
        self._init_ui()

    def _init_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(8)

        title = QLabel(f"🎧 Audio-Video-Matcher – Dragon Tools V{APP_VERSION}")
        title.setStyleSheet("font-weight:bold;font-size:15px;")
        root.addWidget(title)

        hint = QLabel(
            "Vergleicht zwei Videoversionen, erkennt Offset, gleichmäßige Drift oder Schnittunterschiede "
            "und erstellt daraus eine MKV mit Zielvideo und synchronisierter deutscher Audiospur."
        )
        hint.setWordWrap(True)
        root.addWidget(hint)

        file_box = QGroupBox("Dateien")
        grid = QGridLayout(file_box)
        self.source_edit = QLineEdit()
        self.target_edit = QLineEdit()
        self.output_edit = QLineEdit(str(app_documents_dir() / "AudioVideoMatcher" / "synchronisiert.mkv"))
        self.source_btn = QPushButton("📁")
        self.target_btn = QPushButton("📁")
        self.output_btn = QPushButton("📁")
        grid.addWidget(QLabel("Deutsche Quelle:"), 0, 0)
        grid.addWidget(self.source_edit, 0, 1)
        grid.addWidget(self.source_btn, 0, 2)
        grid.addWidget(QLabel("Zielvideo:"), 1, 0)
        grid.addWidget(self.target_edit, 1, 1)
        grid.addWidget(self.target_btn, 1, 2)
        grid.addWidget(QLabel("Ausgabe:"), 2, 0)
        grid.addWidget(self.output_edit, 2, 1)
        grid.addWidget(self.output_btn, 2, 2)
        root.addWidget(file_box)

        result_box = QGroupBox("Analyseergebnis")
        rg = QGridLayout(result_box)
        self.case_value = QLabel("Noch nicht analysiert")
        self.confidence_value = QLabel("-")
        self.offset_value = QLabel("-")
        self.speed_value = QLabel("-")
        self.drift_value = QLabel("-")
        self.common_value = QLabel("-")
        self.audio_combo = QComboBox()
        rg.addWidget(QLabel("Erkannter Fall:"), 0, 0)
        rg.addWidget(self.case_value, 0, 1)
        rg.addWidget(QLabel("Vertrauen:"), 0, 2)
        rg.addWidget(self.confidence_value, 0, 3)
        rg.addWidget(QLabel("Startoffset:"), 1, 0)
        rg.addWidget(self.offset_value, 1, 1)
        rg.addWidget(QLabel("Geschwindigkeitsfaktor:"), 1, 2)
        rg.addWidget(self.speed_value, 1, 3)
        rg.addWidget(QLabel("Drift:"), 2, 0)
        rg.addWidget(self.drift_value, 2, 1)
        rg.addWidget(QLabel("Gemeinsamer Bereich:"), 2, 2)
        rg.addWidget(self.common_value, 2, 3)
        rg.addWidget(QLabel("Deutsche Audiospur:"), 3, 0)
        rg.addWidget(self.audio_combo, 3, 1, 1, 3)
        root.addWidget(result_box)

        c_box = QGroupBox("Fall C – Schnittbereiche")
        cg = QGridLayout(c_box)
        self.cut_ranges = QLineEdit()
        self.cut_ranges.setPlaceholderText("z.B. 1,5-2,5; 15-25; 01:15-01:25;")
        cg.addWidget(QLabel("Ungefähre Bereiche:"), 0, 0)
        cg.addWidget(self.cut_ranges, 0, 1)
        cg.addWidget(InfoButton(
            "Gib Zielvideo-Zeitbereiche ein, in denen sich die Versionen unterscheiden.\n"
            "Eine Genauigkeit von ca. +/- 1 Sekunde reicht.\n\n"
            "Beispiele:\n"
            "1,5-2,5;15-25;\n"
            "01:15-01:25;\n"
            "01:15,500-01:25,800;"
        ), 0, 2)
        self.refine_btn = QPushButton("🔎 Schnittbereiche analysieren")
        self.refine_btn.setEnabled(False)
        root.addWidget(c_box)

        actions = QHBoxLayout()
        self.analyze_btn = QPushButton("🔎 Analysieren")
        self.create_btn = QPushButton("🎧 Audio anpassen und Datei erstellen")
        self.cancel_btn = QPushButton("⛔ Abbrechen")
        self.create_btn.setEnabled(False)
        self.cancel_btn.setEnabled(False)
        self.progress = QProgressBar()
        actions.addWidget(self.analyze_btn)
        actions.addWidget(self.refine_btn)
        actions.addWidget(self.create_btn)
        actions.addWidget(self.cancel_btn)
        actions.addWidget(self.progress, 1)
        root.addLayout(actions)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumBlockCount(3000)
        self.log.setMinimumHeight(180)
        root.addWidget(self.log, 1)

        self.source_btn.clicked.connect(lambda: self._choose_video(self.source_edit, "Deutsche Quellvideodatei wählen"))
        self.target_btn.clicked.connect(lambda: self._choose_video(self.target_edit, "Zielvideodatei wählen"))
        self.output_btn.clicked.connect(self._choose_output)
        self.target_edit.textChanged.connect(self._maybe_update_output_name)
        self.analyze_btn.clicked.connect(self._start_analyze)
        self.refine_btn.clicked.connect(self._start_refine)
        self.create_btn.clicked.connect(self._start_create)
        self.cancel_btn.clicked.connect(self._cancel)

    def _choose_video(self, line: QLineEdit, title: str) -> None:
        files_filter = f"Video-Dateien ({' '.join('*' + ext for ext in sorted(VIDEO_EXTENSIONS))});;Alle Dateien (*)"
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
        target = Path(self.target_edit.text().strip())
        if not target.name:
            return
        current = Path(self.output_edit.text().strip())
        if current.name not in {"", "synchronisiert.mkv"}:
            return
        out_dir = app_documents_dir() / "AudioVideoMatcher"
        self.output_edit.setText(str(out_dir / f"{target.stem}_DE-Sync.mkv"))

    def _start_analyze(self) -> None:
        if not self._validate_paths(require_output=False):
            return
        self._analysis = None
        self._cut_results = []
        self.log.clear()
        self.progress.setValue(0)
        self._set_running(True)
        self._worker = AudioVideoMatchThread(
            "analyze",
            source_path=self.source_edit.text().strip(),
            target_path=self.target_edit.text().strip(),
            parent=self,
        )
        self._wire_worker(self._worker)
        self._worker.analysis_ready.connect(self._analysis_ready)
        self._worker.start()

    def _start_refine(self) -> None:
        if self._analysis is None:
            QMessageBox.information(self, "Audio-Video-Matcher", "Bitte zuerst analysieren.")
            return
        if not self.cut_ranges.text().strip():
            QMessageBox.information(self, "Schnittbereiche", "Bitte mindestens einen ungefähren Schnittbereich eintragen.")
            return
        self.progress.setValue(0)
        self._set_running(True)
        self._worker = AudioVideoMatchThread(
            "refine",
            source_path=self.source_edit.text().strip(),
            target_path=self.target_edit.text().strip(),
            mapping_result=self._analysis,
            cut_ranges_text=self.cut_ranges.text(),
            parent=self,
        )
        self._wire_worker(self._worker)
        self._worker.cuts_ready.connect(self._cuts_ready)
        self._worker.start()

    def _start_create(self) -> None:
        if self._analysis is None:
            QMessageBox.information(self, "Audio-Video-Matcher", "Bitte zuerst analysieren.")
            return
        if not self._validate_paths(require_output=True):
            return
        if Path(self.output_edit.text().strip()).exists():
            QMessageBox.warning(
                self,
                "Ausgabe existiert",
                "Die Ausgabedatei existiert bereits.\nBitte einen neuen Namen wählen.",
            )
            return
        audio_idx = self._selected_audio_index()
        self.progress.setValue(0)
        self._set_running(True)
        self._worker = AudioVideoMatchThread(
            "create",
            source_path=self.source_edit.text().strip(),
            target_path=self.target_edit.text().strip(),
            output_path=self.output_edit.text().strip(),
            audio_stream_index=audio_idx,
            mapping_result=self._analysis,
            cut_results=self._cut_results,
            parent=self,
        )
        self._wire_worker(self._worker)
        self._worker.result_ready.connect(self._result_ready)
        self._worker.start()

    def _wire_worker(self, worker: AudioVideoMatchThread) -> None:
        worker.log_line.connect(self._log)
        worker.progress.connect(self.progress.setValue)
        worker.error.connect(self._error)
        worker.finished.connect(self._finished)

    def iter_shutdown_workers(self) -> tuple:
        return (self._worker,) if self._worker is not None else ()

    def _cancel(self) -> None:
        if self._worker:
            self._worker.cancel()

    def _set_running(self, running: bool) -> None:
        self.analyze_btn.setEnabled(not running)
        self.refine_btn.setEnabled((not running) and self._analysis is not None and self._analysis.mode == "C")
        self.create_btn.setEnabled((not running) and self._can_create())
        self.cancel_btn.setEnabled(running)
        for widget in (self.source_btn, self.target_btn, self.output_btn, self.source_edit, self.target_edit, self.output_edit, self.cut_ranges):
            widget.setEnabled(not running)

    def _finished(self) -> None:
        self._set_running(False)
        self._worker = None

    def _analysis_ready(self, result: TimeMappingResult) -> None:
        self._analysis = result
        self._cut_results = []
        self._render_analysis(result)
        if result.mode == "C" and result.suspect_cut_ranges:
            self.cut_ranges.setText(";".join(
                f"{format_seconds(r.start_s)}-{format_seconds(r.end_s)}"
                for r in result.suspect_cut_ranges
            ))
        self._set_running(False)

    def _cuts_ready(self, cuts: list[CutMatchResult]) -> None:
        self._cut_results = list(cuts or [])
        self._set_running(False)
        if self._analysis:
            unresolved = [c for c in self._cut_results if not c.resolved]
            if unresolved:
                QMessageBox.warning(
                    self,
                    "Schnittbereiche",
                    "Mindestens ein Bereich enthält Zielinhalt ohne deutsche Audioentsprechung. "
                    "Die automatische Erstellung bleibt blockiert.",
                )

    def _result_ready(self, output_path: str) -> None:
        QMessageBox.information(self, "Audio-Video-Matcher", f"Datei erstellt:\n{output_path}")

    def _render_analysis(self, result: TimeMappingResult) -> None:
        labels = {
            "A": "Fall A – Offset",
            "B": "Fall B – Drift",
            "C": "Fall C – Schnittunterschiede",
            "D": "Kein sicheres Match",
        }
        self.case_value.setText(labels.get(result.mode, result.mode))
        self.confidence_value.setText(f"{result.confidence_percent:.1f} %")
        self.offset_value.setText(f"{result.offset_s:+.3f} s")
        self.speed_value.setText(f"{result.speed_factor:.8f}")
        self.drift_value.setText(f"{result.drift_s:.3f} s")
        self.common_value.setText(
            f"{format_seconds(result.common_start_target_s)} – {format_seconds(result.common_end_target_s)}"
        )
        self._render_audio_choice(result)

    def _render_audio_choice(self, result: TimeMappingResult) -> None:
        stream = preferred_german_audio_stream(result.source_info)
        self.audio_combo.clear()
        if stream is None:
            self.audio_combo.addItem("Keine Audiospur gefunden", None)
            return
        preferred_idx = 0
        for idx, audio in enumerate(result.source_info.audio_streams):
            lang = audio.language or "und"
            title = f" | {audio.title}" if audio.title else ""
            bitrate = f" | {int(audio.bitrate / 1000)} kbps" if audio.bitrate else ""
            self.audio_combo.addItem(
                f"#{audio.index} | {lang} | {audio.codec} | {audio.channels}ch{bitrate}{title}",
                int(audio.index),
            )
            if audio.index == stream.index:
                preferred_idx = idx
        self.audio_combo.setCurrentIndex(preferred_idx)

    def _selected_audio_index(self) -> int | None:
        value = self.audio_combo.currentData()
        try:
            return int(value)
        except Exception:
            return None

    def _can_create(self) -> bool:
        if self._analysis is None:
            return False
        if self._analysis.mode in {"A", "B"}:
            return bool(self._analysis.can_process)
        if self._analysis.mode == "C":
            return bool(self._cut_results) and all(c.resolved for c in self._cut_results)
        return False

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

    def _log(self, line: str) -> None:
        self.log.appendPlainText(str(line))

    def _error(self, message: str) -> None:
        QMessageBox.warning(self, "Audio-Video-Matcher", str(message))
