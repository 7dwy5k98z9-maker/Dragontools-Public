from __future__ import annotations

from PyQt6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QProgressBar,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
)


class ISOWidgetViewMixin:
    """Builds and toggles the ISO widget UI; contains no worker logic."""

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)

        root.addWidget(QLabel("ISO-Handling / Disc-Import"))
        structure_hint = QLabel(
            "Unterstützt werden ISO/IMG-Dateien, Disc-Root-Ordner und direkt ausgewählte BDMV-/VIDEO_TS-Ordner. "
            "Blu-ray-Struktur: Disc-Ordner\\BDMV\\index.bdmv, PLAYLIST\\*.mpls, STREAM\\*.m2ts, CLIPINF\\*.clpi; "
            "CERTIFICATE ist optional. MakeMKV ist der bevorzugte Weg, FFmpeg dient nur als Fallback."
        )
        structure_hint.setWordWrap(True)
        structure_hint.setStyleSheet("color: #444;")
        root.addWidget(structure_hint)

        self.input_list = QListWidget()
        self.input_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        root.addWidget(self.input_list)

        input_btns = QHBoxLayout()
        self._btn_add_iso = QPushButton("➕ ISO-Dateien")
        self._btn_add_iso.clicked.connect(self._add_iso_files)
        self._btn_add_folder = QPushButton("📁 Disc-Ordner")
        self._btn_add_folder.clicked.connect(self._add_disc_folder)
        self._btn_remove = QPushButton("➖ Entfernen")
        self._btn_remove.clicked.connect(self._remove_selected)
        self._btn_clear = QPushButton("🗑️ Alle")
        self._btn_clear.clicked.connect(self._clear_inputs)
        self._btn_analyze = QPushButton("Titel analysieren")
        self._btn_analyze.clicked.connect(self._analyze)
        input_btns.addWidget(self._btn_add_iso)
        input_btns.addWidget(self._btn_add_folder)
        input_btns.addWidget(self._btn_remove)
        input_btns.addWidget(self._btn_clear)
        input_btns.addWidget(self._btn_analyze)
        root.addLayout(input_btns)

        root.addWidget(QLabel("Titel-Auswahl:"))
        self.title_list = QListWidget()
        self.title_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        root.addWidget(self.title_list)

        out_row = QHBoxLayout()
        out_row.addWidget(QLabel("Zielpfad:"))
        self.output_edit = QLineEdit()
        out_row.addWidget(self.output_edit)
        self._btn_browse = QPushButton("Durchsuchen")
        self._btn_browse.clicked.connect(self._browse_output)
        out_row.addWidget(self._btn_browse)
        root.addLayout(out_row)

        self.auto_main_title_cb = QCheckBox("Haupttitel automatisch vorschlagen")
        self.auto_main_title_cb.setChecked(True)
        root.addWidget(self.auto_main_title_cb)

        self.auto_series_disc_cb = QCheckBox("Serien-Disc automatisch erkennen")
        self.auto_series_disc_cb.setChecked(True)
        self.auto_series_disc_cb.setToolTip(
            "Erkennt mehrere ähnlich lange Titel als einzelne Episoden und bevorzugt sie "
            "gegenüber einem langen 'Alle abspielen'-Sammeltitel. Abschalten verwendet "
            "wieder ausschließlich den längsten Haupttitel."
        )
        root.addWidget(self.auto_series_disc_cb)

        self.ffmpeg_fallback_cb = QCheckBox("FFmpeg-Fallback verwenden, wenn MakeMKV scheitert")
        self.ffmpeg_fallback_cb.setChecked(True)
        self.ffmpeg_fallback_cb.setToolTip(
            "Versucht bei fehlender/ungültiger MakeMKV-Freischaltung oder MakeMKV-Fehlern "
            "einen reinen FFmpeg-Remux. Funktioniert nur bei unverschlüsselten, direkt lesbaren "
            "ISO-/Disc-Strukturen und ist weniger zuverlässig als MakeMKV."
        )
        root.addWidget(self.ffmpeg_fallback_cb)

        self.handoff_cb = QCheckBox("Nach Extraktion an Konverter übergeben")
        root.addWidget(self.handoff_cb)

        btn_row = QHBoxLayout()
        self._btn_start = QPushButton("Extraktion starten")
        self._btn_start.clicked.connect(self._start)
        self._btn_abort = QPushButton("Abbrechen")
        self._btn_abort.clicked.connect(self._abort)
        self._btn_abort.setEnabled(False)
        btn_row.addWidget(self._btn_start)
        btn_row.addWidget(self._btn_abort)
        root.addLayout(btn_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        root.addWidget(self.progress_bar)

        self.log_edit = QTextEdit()
        self.log_edit.setReadOnly(True)
        root.addWidget(self.log_edit)

    def _set_running(self, running: bool) -> None:
        for widget in (
            self.input_list,
            self.title_list,
            self.output_edit,
            self.auto_main_title_cb,
            self.auto_series_disc_cb,
            self.ffmpeg_fallback_cb,
            self.handoff_cb,
            self._btn_add_iso,
            self._btn_add_folder,
            self._btn_remove,
            self._btn_clear,
            self._btn_analyze,
            self._btn_browse,
            self._btn_start,
        ):
            if widget is not None:
                widget.setEnabled(not running)
        if self._btn_abort is not None:
            self._btn_abort.setEnabled(running)
