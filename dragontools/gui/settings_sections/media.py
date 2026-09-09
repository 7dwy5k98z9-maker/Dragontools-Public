# -*- coding: utf-8 -*-
from __future__ import annotations
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFileDialog, QGridLayout, QGroupBox, QLabel, QLineEdit, QPushButton, QSpinBox, QWidget
from ...core import settings as cfg
from ...core.media_library_types import default_media_library_db_path
from ..info_button import InfoButton
from .base import SettingsSection


class MediaPostprocessSection(SettingsSection):
    section_keys = ("media_library", "postprocess", "source_visual")

    def build(self, vl) -> None:
        d = self.dialog
        # ── Mediathek-Datenbank ─────────────────────────────────────────
        library_grp = QGroupBox("Mediathek-Datenbank")
        d._section_widgets["media_library"] = library_grp
        lg = QGridLayout(library_grp)
        library_desc = QLabel(
            "Optionale eigene SQLite-Datenbank für schnelle Bestandssuche, Jellyfin-Import "
            "und Preflight-Zielordner ohne NAS-Vollsuche."
        )
        library_desc.setWordWrap(True)
        lg.addWidget(library_desc, 0, 0, 1, 4)

        d.media_library_enabled_cb = QCheckBox("Mediathek-Datenbank verwenden")
        lg.addWidget(d.media_library_enabled_cb, 1, 0, 1, 3)
        lg.addWidget(InfoButton(
            "Aktiviert die DragonTools-eigene Datenbank. Jellyfin wird dabei nie direkt verändert."
        ), 1, 3)

        d.media_library_preflight_cb = QCheckBox("Preflight bevorzugt aus der Datenbank auflösen")
        lg.addWidget(d.media_library_preflight_cb, 2, 0, 1, 3)
        lg.addWidget(InfoButton(
            "Wenn eine Serie in der Mediathek bekannt ist, nutzt der Preflight den gespeicherten Zielordner "
            "und durchsucht die NAS erst danach als Fallback."
        ), 2, 3)

        lg.addWidget(QLabel("Datenbank:"), 3, 0)
        d.media_library_db_edit = QLineEdit()
        lg.addWidget(d.media_library_db_edit, 3, 1)
        db_browse_btn = QPushButton("…")
        db_browse_btn.setFixedWidth(28)
        db_browse_btn.clicked.connect(d.browse_media_library_db)
        lg.addWidget(db_browse_btn, 3, 2)
        lg.addWidget(InfoButton(
            "Standard ist Dokumente\\DragonTools\\Mediathek\\dragontools_mediathek.sqlite3."
        ), 3, 3)

        open_library_btn = QPushButton("Mediathek-Dialog öffnen")
        open_library_btn.clicked.connect(d.open_media_library_dialog)
        lg.addWidget(open_library_btn, 4, 1, 1, 2)
        vl.addWidget(library_grp)

        # ── Jellyfin NFO / Trickplay ─────────────────────────────────────
        pp_grp = QGroupBox("Jellyfin NFO / Trickplay")
        d._section_widgets["postprocess"] = pp_grp
        ppg = QGridLayout(pp_grp)
        desc = QLabel(
            "Optionale Zusatzdateien nach erfolgreicher Konvertierung. "
            "Beim späteren Verschieben werden NFO- und Trickplay-Daten zusammen mit dem Video verschoben."
        )
        desc.setWordWrap(True)
        ppg.addWidget(desc, 0, 0, 1, 3)

        d.nfo_enabled_cb = QCheckBox("Jellyfin-NFO nach erfolgreicher Konvertierung erstellen")
        ppg.addWidget(d.nfo_enabled_cb, 1, 0, 1, 2)
        ppg.addWidget(InfoButton(
            "Erstellt eine Film- oder Folgen-NFO aus der konfigurierten Online-Metadatenquelle. "
            "Filme werden beim Verschieben in Filmordner automatisch zu movie.nfo umbenannt."
        ), 1, 2)
        d.nfo_only_unambiguous_cb = QCheckBox("Nur bei eindeutigem Treffer erstellen")
        ppg.addWidget(d.nfo_only_unambiguous_cb, 2, 0, 1, 2)
        ppg.addWidget(InfoButton(
            "Wenn kein plausibler Metadaten-Treffer vorhanden ist, wird keine NFO geschrieben."
        ), 2, 2)
        d.nfo_fileinfo_cb = QCheckBox("Technische Dateiinfos eintragen")
        ppg.addWidget(d.nfo_fileinfo_cb, 3, 0, 1, 2)
        ppg.addWidget(InfoButton(
            "Schreibt Video-/Audio-/Untertitel-Details aus ffprobe in den fileinfo-Bereich der NFO."
        ), 3, 2)
        ppg.addWidget(QLabel("Film-NFO im Ziel:"), 4, 0)
        d.nfo_movie_name_combo = QComboBox()
        d.nfo_movie_name_combo.addItem("movie.nfo (Jellyfin-Standard)", "movie.nfo")
        d.nfo_movie_name_combo.addItem("Filmname.nfo behalten", "stem")
        ppg.addWidget(d.nfo_movie_name_combo, 4, 1)
        ppg.addWidget(InfoButton(
            "Für deine Filmordner ist movie.nfo sinnvoll. In der Arbeitsablage bleibt die NFO bis zum Verschieben eindeutig benannt."
        ), 4, 2)
        ppg.addWidget(QLabel("NFO-Konflikt:"), 5, 0)
        d.nfo_conflict_combo = QComboBox()
        d.nfo_conflict_combo.addItem("Vorhandene NFO behalten", "skip")
        d.nfo_conflict_combo.addItem("Vorhandene NFO ersetzen", "overwrite")
        d.nfo_conflict_combo.addItem("Vorhandene NFO vorher sichern", "backup")
        ppg.addWidget(d.nfo_conflict_combo, 5, 1)
        ppg.addWidget(InfoButton(
            "Gilt für die NFO im Arbeitsordner. Beim finalen Verschieben greift zusätzlich dein normales Konfliktverhalten."
        ), 5, 2)

        d.trickplay_enabled_cb = QCheckBox("Jellyfin-Trickplaybilder erstellen")
        ppg.addWidget(d.trickplay_enabled_cb, 6, 0, 1, 2)
        ppg.addWidget(InfoButton(
            "Erstellt Jellyfin-kompatible Kachelbilder im Ordner Filmname.trickplay."
        ), 6, 2)
        ppg.addWidget(QLabel("Trickplay-Konflikt:"), 7, 0)
        d.trickplay_conflict_combo = QComboBox()
        d.trickplay_conflict_combo.addItem("Vorhandene Trickplaybilder behalten", "skip")
        d.trickplay_conflict_combo.addItem("Vorhandene Trickplaybilder ersetzen", "overwrite")
        d.trickplay_conflict_combo.addItem("Vorhandene Trickplaybilder vorher sichern", "backup")
        ppg.addWidget(d.trickplay_conflict_combo, 7, 1)
        ppg.addWidget(InfoButton(
            "Gilt beim Erzeugen und beim späteren Verschieben des Filmname.trickplay-Ordners."
        ), 7, 2)

        ppg.addWidget(QLabel("Trickplay-Quelle:"), 8, 0)
        d.trickplay_source_combo = QComboBox()
        d.trickplay_source_combo.addItem("Konvertierte Ausgabedatei", "output")
        d.trickplay_source_combo.addItem("Ausgangsmaterial", "source")
        ppg.addWidget(d.trickplay_source_combo, 8, 1)
        ppg.addWidget(InfoButton(
            "Ausgabedatei ist am sichersten, weil die Vorschauen exakt zur fertigen Datei passen. "
            "Ausgangsmaterial kann schneller sein, wenn nach der Konvertierung nicht erneut aus der neuen Datei gelesen werden soll."
        ), 8, 2)

        ppg.addWidget(QLabel("Bildbreite:"), 9, 0)
        d.trickplay_width_spin = QSpinBox()
        d.trickplay_width_spin.setRange(160, 1024)
        d.trickplay_width_spin.setSingleStep(20)
        d.trickplay_width_spin.setSuffix(" px")
        ppg.addWidget(d.trickplay_width_spin, 9, 1)
        ppg.addWidget(InfoButton("Jellyfin-Standard: 320 px Breite."), 9, 2)

        ppg.addWidget(QLabel("Kachelraster:"), 10, 0)
        d.trickplay_cols_spin = QSpinBox()
        d.trickplay_cols_spin.setRange(1, 20)
        d.trickplay_cols_spin.setSuffix(" Spalten")
        d.trickplay_rows_spin = QSpinBox()
        d.trickplay_rows_spin.setRange(1, 20)
        d.trickplay_rows_spin.setSuffix(" Zeilen")
        raster_row = QWidget()
        raster_layout = QGridLayout(raster_row)
        raster_layout.setContentsMargins(0, 0, 0, 0)
        raster_layout.addWidget(d.trickplay_cols_spin, 0, 0)
        raster_layout.addWidget(d.trickplay_rows_spin, 0, 1)
        ppg.addWidget(raster_row, 10, 1)
        ppg.addWidget(InfoButton("Jellyfin-Standard: 10x10 Kacheln je JPG."), 10, 2)

        ppg.addWidget(QLabel("Intervall:"), 11, 0)
        d.trickplay_interval_spin = QSpinBox()
        d.trickplay_interval_spin.setRange(1, 120)
        d.trickplay_interval_spin.setSuffix(" s")
        ppg.addWidget(d.trickplay_interval_spin, 11, 1)
        ppg.addWidget(InfoButton("Abstand zwischen zwei Vorschaubildern. Jellyfin-Standard: 10 s."), 11, 2)

        ppg.addWidget(QLabel("JPEG-Qualität:"), 12, 0)
        d.trickplay_jpeg_quality_spin = QSpinBox()
        d.trickplay_jpeg_quality_spin.setRange(1, 100)
        d.trickplay_jpeg_quality_spin.setSuffix(" %")
        ppg.addWidget(d.trickplay_jpeg_quality_spin, 12, 1)
        ppg.addWidget(InfoButton(
            "Kompatibilitätswert für deine Jellyfin-Konfiguration. "
            "Die FFmpeg-Erzeugung steuert die echte JPG-Qualität über qscale."
        ), 12, 2)

        ppg.addWidget(QLabel("qscale:"), 13, 0)
        d.trickplay_qscale_spin = QSpinBox()
        d.trickplay_qscale_spin.setRange(2, 31)
        ppg.addWidget(d.trickplay_qscale_spin, 13, 1)
        ppg.addWidget(InfoButton("FFmpeg-JPEG-Qualität: kleiner ist besser. Jellyfin-Standard: 4."), 13, 2)

        ppg.addWidget(QLabel("Hardware:"), 14, 0)
        d.trickplay_hwaccel_combo = QComboBox()
        d.trickplay_hwaccel_combo.addItem("NVIDIA CUDA/NVDEC-Decoding mit CPU-Fallback", "cuda")
        d.trickplay_hwaccel_combo.addItem("CPU", "none")
        ppg.addWidget(d.trickplay_hwaccel_combo, 14, 1)
        ppg.addWidget(InfoButton(
            "CUDA/NVDEC beschleunigt das Decoding. Die Kachel-Filter laufen kompatibel weiter; "
            "falls der Hardwarepfad bei einer Datei nicht klappt, wird automatisch CPU versucht."
        ), 14, 2)

        ppg.addWidget(QLabel("Max. Trickplay-Jobs:"), 15, 0)
        d.trickplay_max_jobs_spin = QSpinBox()
        d.trickplay_max_jobs_spin.setRange(1, 8)
        d.trickplay_max_jobs_spin.setSuffix(" Job(s)")
        ppg.addWidget(d.trickplay_max_jobs_spin, 15, 1)
        ppg.addWidget(InfoButton(
            "Begrenzt nur gleichzeitige Trickplay-Erstellung im Parallelbetrieb. Standard: 1."
        ), 15, 2)
        vl.addWidget(pp_grp)

        # ── Quellbildprüfung ──────────────────────────────────────────────
        source_grp = QGroupBox("Quellbildprüfung")
        d._section_widgets["source_visual"] = source_grp
        svg = QGridLayout(source_grp)
        source_desc = QLabel(
            "Prüft vor der Konvertierung mehrere kurze Bildausschnitte. "
            "Bei eindeutig defektem Material wird die Datei übersprungen, bis sie per Rechtsklick freigegeben wird."
        )
        source_desc.setWordWrap(True)
        svg.addWidget(source_desc, 0, 0, 1, 3)

        d.source_visual_enabled_cb = QCheckBox("Quellbildprüfung vor Konvertierung aktivieren")
        svg.addWidget(d.source_visual_enabled_cb, 1, 0, 1, 2)
        svg.addWidget(InfoButton(
            "Die Prüfung sucht nach komplett leeren, einfarbig auffälligen oder stark verrauschten Bildausschnitten. "
            "Sie ersetzt keine manuelle Sichtprüfung, verhindert aber klare Defektfälle."
        ), 1, 2)

        svg.addWidget(QLabel("Prüfintervall:"), 2, 0)
        d.source_visual_interval_spin = QSpinBox()
        d.source_visual_interval_spin.setRange(5, 50)
        d.source_visual_interval_spin.setSingleStep(5)
        d.source_visual_interval_spin.setSuffix(" %")
        svg.addWidget(d.source_visual_interval_spin, 2, 1)
        svg.addWidget(InfoButton("10 % prüft die Positionen 10, 20, 30 ... 90 % der Laufzeit."), 2, 2)

        svg.addWidget(QLabel("Prüfdauer je Punkt:"), 3, 0)
        d.source_visual_duration_spin = QSpinBox()
        d.source_visual_duration_spin.setRange(1, 10)
        d.source_visual_duration_spin.setSuffix(" s")
        svg.addWidget(d.source_visual_duration_spin, 3, 1)
        svg.addWidget(InfoButton("2 Sekunden sind ein guter Kompromiss aus Tempo und Stabilität."), 3, 2)

        svg.addWidget(QLabel("Frames pro Sekunde:"), 4, 0)
        d.source_visual_fps_spin = QSpinBox()
        d.source_visual_fps_spin.setRange(1, 10)
        d.source_visual_fps_spin.setSuffix(" fps")
        svg.addWidget(d.source_visual_fps_spin, 4, 1)
        svg.addWidget(InfoButton("Mehr Frames erhöhen die Sicherheit, verlängern aber die Vorprüfung."), 4, 2)

        svg.addWidget(QLabel("Blockieren ab:"), 5, 0)
        d.source_visual_block_spin = QSpinBox()
        d.source_visual_block_spin.setRange(50, 100)
        d.source_visual_block_spin.setSuffix(" % auffällig")
        svg.addWidget(d.source_visual_block_spin, 5, 1)
        svg.addWidget(InfoButton("Standard 80 %: erst bei sehr vielen auffälligen Prüfpunkten wird blockiert."), 5, 2)

        svg.addWidget(QLabel("Mindestens auffällige Punkte:"), 6, 0)
        d.source_visual_min_hits_spin = QSpinBox()
        d.source_visual_min_hits_spin.setRange(1, 20)
        svg.addWidget(d.source_visual_min_hits_spin, 6, 1)
        svg.addWidget(InfoButton("Verhindert, dass sehr kurze Dateien wegen einzelner Prüfpunkte blockiert werden."), 6, 2)
        vl.addWidget(source_grp)


    def load(self) -> None:
        d, s = self.dialog, self.settings
        d.media_library_enabled_cb.setChecked(s.value(cfg.SET_KEY_MEDIA_LIBRARY_ENABLED, cfg.DEFAULT_MEDIA_LIBRARY_ENABLED, type=bool))
        d.media_library_preflight_cb.setChecked(s.value(cfg.SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED, cfg.DEFAULT_MEDIA_LIBRARY_PREFLIGHT_ENABLED, type=bool))
        d.media_library_db_edit.setText(s.value(cfg.SET_KEY_MEDIA_LIBRARY_DB_PATH, str(default_media_library_db_path()), type=str))

        d.nfo_enabled_cb.setChecked(s.value(cfg.SET_KEY_NFO_ENABLED, cfg.DEFAULT_NFO_ENABLED, type=bool))
        d.nfo_only_unambiguous_cb.setChecked(s.value(cfg.SET_KEY_NFO_ONLY_UNAMBIGUOUS, cfg.DEFAULT_NFO_ONLY_UNAMBIGUOUS, type=bool))
        d.nfo_fileinfo_cb.setChecked(s.value(cfg.SET_KEY_NFO_FILEINFO_ENABLED, cfg.DEFAULT_NFO_FILEINFO_ENABLED, type=bool))
        nfo_name = s.value(cfg.SET_KEY_NFO_MOVIE_TARGET_NAME, cfg.DEFAULT_NFO_MOVIE_TARGET_NAME, type=str)
        idx = d.nfo_movie_name_combo.findData(nfo_name)
        d.nfo_movie_name_combo.setCurrentIndex(idx if idx >= 0 else 0)
        nfo_conflict = s.value(cfg.SET_KEY_NFO_CONFLICT_MODE, cfg.DEFAULT_NFO_CONFLICT_MODE, type=str)
        idx = d.nfo_conflict_combo.findData(nfo_conflict)
        d.nfo_conflict_combo.setCurrentIndex(idx if idx >= 0 else 0)

        d.trickplay_enabled_cb.setChecked(s.value(cfg.SET_KEY_TRICKPLAY_ENABLED, cfg.DEFAULT_TRICKPLAY_ENABLED, type=bool))
        trickplay_conflict = s.value(cfg.SET_KEY_TRICKPLAY_CONFLICT_MODE, "", type=str)
        if trickplay_conflict not in {"skip", "overwrite", "backup"}:
            only_missing = s.value(cfg.SET_KEY_TRICKPLAY_ONLY_MISSING, cfg.DEFAULT_TRICKPLAY_ONLY_MISSING, type=bool)
            trickplay_conflict = "skip" if only_missing else "overwrite"
        if trickplay_conflict not in {"skip", "overwrite", "backup"}:
            trickplay_conflict = cfg.DEFAULT_TRICKPLAY_CONFLICT_MODE
        idx = d.trickplay_conflict_combo.findData(trickplay_conflict)
        d.trickplay_conflict_combo.setCurrentIndex(idx if idx >= 0 else 0)
        trickplay_source = s.value(cfg.SET_KEY_TRICKPLAY_SOURCE_MODE, cfg.DEFAULT_TRICKPLAY_SOURCE_MODE, type=str)
        idx = d.trickplay_source_combo.findData(trickplay_source)
        d.trickplay_source_combo.setCurrentIndex(idx if idx >= 0 else 0)
        d.trickplay_width_spin.setValue(int(s.value(cfg.SET_KEY_TRICKPLAY_WIDTH, cfg.DEFAULT_TRICKPLAY_WIDTH, type=int)))
        d.trickplay_cols_spin.setValue(int(s.value(cfg.SET_KEY_TRICKPLAY_TILE_COLUMNS, cfg.DEFAULT_TRICKPLAY_TILE_COLUMNS, type=int)))
        d.trickplay_rows_spin.setValue(int(s.value(cfg.SET_KEY_TRICKPLAY_TILE_ROWS, cfg.DEFAULT_TRICKPLAY_TILE_ROWS, type=int)))
        d.trickplay_interval_spin.setValue(int(s.value(cfg.SET_KEY_TRICKPLAY_INTERVAL_S, cfg.DEFAULT_TRICKPLAY_INTERVAL_S, type=int)))
        d.trickplay_jpeg_quality_spin.setValue(int(s.value(cfg.SET_KEY_TRICKPLAY_JPEG_QUALITY, cfg.DEFAULT_TRICKPLAY_JPEG_QUALITY, type=int)))
        d.trickplay_qscale_spin.setValue(int(s.value(cfg.SET_KEY_TRICKPLAY_QSCALE, cfg.DEFAULT_TRICKPLAY_QSCALE, type=int)))
        hwaccel = s.value(cfg.SET_KEY_TRICKPLAY_HWACCEL, cfg.DEFAULT_TRICKPLAY_HWACCEL, type=str)
        idx = d.trickplay_hwaccel_combo.findData(hwaccel)
        d.trickplay_hwaccel_combo.setCurrentIndex(idx if idx >= 0 else 0)
        d.trickplay_max_jobs_spin.setValue(int(s.value(cfg.SET_KEY_TRICKPLAY_MAX_JOBS, cfg.DEFAULT_TRICKPLAY_MAX_JOBS, type=int)))

        d.source_visual_enabled_cb.setChecked(s.value(cfg.SET_KEY_SOURCE_VISUAL_CHECK_ENABLED, cfg.DEFAULT_SOURCE_VISUAL_CHECK_ENABLED, type=bool))
        d.source_visual_interval_spin.setValue(int(s.value(cfg.SET_KEY_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT, cfg.DEFAULT_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT, type=int)))
        d.source_visual_duration_spin.setValue(int(s.value(cfg.SET_KEY_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S, cfg.DEFAULT_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S, type=int)))
        d.source_visual_fps_spin.setValue(int(s.value(cfg.SET_KEY_SOURCE_VISUAL_CHECK_FPS, cfg.DEFAULT_SOURCE_VISUAL_CHECK_FPS, type=int)))
        d.source_visual_block_spin.setValue(int(s.value(cfg.SET_KEY_SOURCE_VISUAL_CHECK_BLOCK_PERCENT, cfg.DEFAULT_SOURCE_VISUAL_CHECK_BLOCK_PERCENT, type=int)))
        d.source_visual_min_hits_spin.setValue(int(s.value(cfg.SET_KEY_SOURCE_VISUAL_CHECK_MIN_HITS, cfg.DEFAULT_SOURCE_VISUAL_CHECK_MIN_HITS, type=int)))

    def save(self) -> bool:
        d, s = self.dialog, self.settings
        s.setValue(cfg.SET_KEY_MEDIA_LIBRARY_ENABLED, d.media_library_enabled_cb.isChecked())
        s.setValue(cfg.SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED, d.media_library_preflight_cb.isChecked())
        s.setValue(cfg.SET_KEY_MEDIA_LIBRARY_DB_PATH, d.media_library_db_edit.text().strip() or str(default_media_library_db_path()))
        s.setValue(cfg.SET_KEY_NFO_ENABLED, d.nfo_enabled_cb.isChecked())
        s.setValue(cfg.SET_KEY_NFO_ONLY_UNAMBIGUOUS, d.nfo_only_unambiguous_cb.isChecked())
        s.setValue(cfg.SET_KEY_NFO_FILEINFO_ENABLED, d.nfo_fileinfo_cb.isChecked())
        s.setValue(cfg.SET_KEY_NFO_MOVIE_TARGET_NAME, d.nfo_movie_name_combo.currentData() or cfg.DEFAULT_NFO_MOVIE_TARGET_NAME)
        s.setValue(cfg.SET_KEY_NFO_CONFLICT_MODE, d.nfo_conflict_combo.currentData() or cfg.DEFAULT_NFO_CONFLICT_MODE)
        s.setValue(cfg.SET_KEY_TRICKPLAY_ENABLED, d.trickplay_enabled_cb.isChecked())
        trickplay_conflict = d.trickplay_conflict_combo.currentData() or cfg.DEFAULT_TRICKPLAY_CONFLICT_MODE
        s.setValue(cfg.SET_KEY_TRICKPLAY_CONFLICT_MODE, trickplay_conflict)
        s.setValue(cfg.SET_KEY_TRICKPLAY_ONLY_MISSING, trickplay_conflict == "skip")
        s.setValue(cfg.SET_KEY_TRICKPLAY_SOURCE_MODE, d.trickplay_source_combo.currentData() or cfg.DEFAULT_TRICKPLAY_SOURCE_MODE)
        s.setValue(cfg.SET_KEY_TRICKPLAY_WIDTH, d.trickplay_width_spin.value())
        s.setValue(cfg.SET_KEY_TRICKPLAY_TILE_COLUMNS, d.trickplay_cols_spin.value())
        s.setValue(cfg.SET_KEY_TRICKPLAY_TILE_ROWS, d.trickplay_rows_spin.value())
        s.setValue(cfg.SET_KEY_TRICKPLAY_INTERVAL_S, d.trickplay_interval_spin.value())
        s.setValue(cfg.SET_KEY_TRICKPLAY_JPEG_QUALITY, d.trickplay_jpeg_quality_spin.value())
        s.setValue(cfg.SET_KEY_TRICKPLAY_QSCALE, d.trickplay_qscale_spin.value())
        s.setValue(cfg.SET_KEY_TRICKPLAY_HWACCEL, d.trickplay_hwaccel_combo.currentData() or cfg.DEFAULT_TRICKPLAY_HWACCEL)
        s.setValue(cfg.SET_KEY_TRICKPLAY_MAX_JOBS, d.trickplay_max_jobs_spin.value())
        s.setValue(cfg.SET_KEY_SOURCE_VISUAL_CHECK_ENABLED, d.source_visual_enabled_cb.isChecked())
        s.setValue(cfg.SET_KEY_SOURCE_VISUAL_CHECK_INTERVAL_PERCENT, d.source_visual_interval_spin.value())
        s.setValue(cfg.SET_KEY_SOURCE_VISUAL_CHECK_SAMPLE_DURATION_S, d.source_visual_duration_spin.value())
        s.setValue(cfg.SET_KEY_SOURCE_VISUAL_CHECK_FPS, d.source_visual_fps_spin.value())
        s.setValue(cfg.SET_KEY_SOURCE_VISUAL_CHECK_BLOCK_PERCENT, d.source_visual_block_spin.value())
        s.setValue(cfg.SET_KEY_SOURCE_VISUAL_CHECK_MIN_HITS, d.source_visual_min_hits_spin.value())
        return True

    def browse_database(self) -> None:
        d = self.dialog
        path, _ = QFileDialog.getSaveFileName(
            d,
            "DragonTools-Mediathek wählen",
            d.media_library_db_edit.text().strip() or str(default_media_library_db_path()),
            "SQLite-Datenbanken (*.sqlite *.sqlite3 *.db);;Alle Dateien (*)",
        )
        if path:
            d.media_library_db_edit.setText(path)

    def open_media_library_dialog(self) -> None:
        d = self.dialog
        from ..media_library_dialog import MediaLibraryDialog
        dlg = MediaLibraryDialog(d, initial_tab="status")
        dlg.exec()
        d.media_library_enabled_cb.setChecked(self.settings.value(cfg.SET_KEY_MEDIA_LIBRARY_ENABLED, cfg.DEFAULT_MEDIA_LIBRARY_ENABLED, type=bool))
        d.media_library_preflight_cb.setChecked(self.settings.value(cfg.SET_KEY_MEDIA_LIBRARY_PREFLIGHT_ENABLED, cfg.DEFAULT_MEDIA_LIBRARY_PREFLIGHT_ENABLED, type=bool))
        d.media_library_db_edit.setText(self.settings.value(cfg.SET_KEY_MEDIA_LIBRARY_DB_PATH, str(default_media_library_db_path()), type=str))
