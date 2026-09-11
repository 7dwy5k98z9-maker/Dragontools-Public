# -*- coding: utf-8 -*-
"""Reiner View-Aufbau für den Mediathek-Dialog.

Die View erstellt Widgets und verbindet sie mit einem Actions-Objekt. Sie kennt
keine Datenbank-, Such-, Mapping- oder Exportlogik.
"""
from __future__ import annotations

from typing import Protocol

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)


SEARCH_MODES = [
    ("Alle Einträge", "all"),
    ("Audio", "audio"),
    ("HDR / Dynamikumfang", "dynamic_range"),
    ("Auflösung", "resolution"),
    ("Video-Codec", "video_codec"),
    ("Dateigröße", "file_size"),
    ("Laufzeitprüfung", "duration"),
    ("Abweichungen", "deviation"),
    ("NFO / NFO-Prüfung", "nfo"),
    ("Metadaten", "metadata"),
]

SEARCH_SCOPES = [
    ("Alle Bereiche", "all"),
    ("Filme", "movies"),
    ("Anime", "anime"),
    ("TV", "tv"),
    ("Serien gesamt", "series"),
    ("Sonstige", "other"),
]

SEARCH_ITEM_TYPES = [
    ("Alle Typen", "all"),
    ("Nur Videodateien", "videos"),
    ("Filme", "movies"),
    ("Serien", "series"),
    ("Staffeln", "seasons"),
    ("Episoden", "episodes"),
    ("Ordner", "folders"),
]

SEARCH_OPTIONS = {
    "all": [("Alle Einträge", "all")],
    "audio": [
        ("Mit deutscher Audiospur", "has_german_audio"),
        ("Ohne deutsche Audiospur", "no_german_audio"),
        ("Mit mehreren Audiospuren", "multiple_audio"),
        ("Stereo / 2.0", "audio_stereo"),
        ("5.1 / 6 Kanäle", "audio_51"),
        ("7.1 / 8+ Kanäle", "audio_71"),
        ("AAC", "audio_codec_aac"),
        ("AC3", "audio_codec_ac3"),
        ("EAC3", "audio_codec_eac3"),
        ("TrueHD", "audio_codec_truehd"),
        ("DTS", "audio_codec_dts"),
        ("FLAC", "audio_codec_flac"),
        ("Audio-Codec unbekannt", "audio_codec_unknown"),
    ],
    "dynamic_range": [
        ("SDR", "sdr"),
        ("HDR", "hdr"),
        ("HDR10+", "hdr10plus"),
        ("Dolby Vision", "dv"),
        ("HDR/SDR unbekannt", "dynamic_range_unknown"),
    ],
    "resolution": [
        ("Kleiner als HD", "resolution_sd"),
        ("HD / 720p", "resolution_hd"),
        ("Full HD / 1080p", "resolution_fhd"),
        ("QHD / 1440p", "resolution_qhd"),
        ("4K / UHD", "resolution_uhd"),
        ("Auflösung unbekannt", "resolution_unknown"),
    ],
    "video_codec": [
        ("H.264 / AVC", "h264"),
        ("H.265 / HEVC", "hevc"),
        ("AV1", "av1"),
        ("Video-Codec unbekannt", "video_codec_unknown"),
    ],
    "file_size": [
        ("Kleiner als 1 GiB", "size_under_1gb"),
        ("1 bis unter 2 GiB", "size_1_2gb"),
        ("2 bis unter 5 GiB", "size_2_5gb"),
        ("5 bis unter 10 GiB", "size_5_10gb"),
        ("10 bis unter 20 GiB", "size_10_20gb"),
        ("20 GiB oder größer", "size_over_20gb"),
        ("Dateigröße unbekannt", "size_unknown"),
    ],
    "duration": [
        ("Länger als 5 Stunden", "duration_over_5h"),
        ("Kürzer als 1 Minute", "duration_under_1min"),
        ("Laufzeit unbekannt", "duration_unknown"),
    ],
    "deviation": [
        ("Deutsche Audiospur", "deviation_german_audio"),
        ("Auflösung", "deviation_resolution"),
        ("Video-Codec", "deviation_video_codec"),
        ("HDR / SDR", "deviation_dynamic_range"),
        ("Audio-Codec", "deviation_audio_codec"),
        ("Audiokanäle", "deviation_audio_channels"),
        ("Anzahl Audiospuren", "deviation_audio_track_count"),
    ],
    "nfo": [
        ("NFO vorhanden", "nfo_present"),
        ("NFO fehlt", "nfo_missing"),
        ("NFO-Speicherpfad nicht erreichbar", "nfo_unreachable"),
        ("NFO ungültig / nicht lesbar", "nfo_invalid"),
        ("NFO noch nicht geprüft", "nfo_unknown"),
        ("NFO mit Abweichungen", "nfo_has_issues"),
        ("NFO mit Fehlern", "nfo_errors"),
        ("NFO mit Warnungen", "nfo_warnings"),
        ("Provider-ID stimmt nicht", "nfo_provider_mismatch"),
    ],
    "metadata": [
        ("Unvollständige / fehlende Metadaten", "metadata_incomplete"),
        ("Videoeigenschaften unbekannt", "video_properties_unknown"),
        ("Doppelte aktive SxxExx", "duplicate_active_sxxexx"),
    ],
}


class MediaLibraryDialogActions(Protocol):
    def update_enabled_state(self, enabled: bool) -> None: ...
    def browse_db_path(self) -> None: ...
    def browse_jellyfin_db(self) -> None: ...
    def create_empty_database(self) -> None: ...
    def import_jellyfin(self) -> None: ...
    def scan_storage_paths(self) -> None: ...
    def abort_storage_scan(self) -> None: ...
    def scan_nfo_light(self) -> None: ...
    def scan_nfo_full(self) -> None: ...
    def abort_nfo_scan(self) -> None: ...
    def export_database(self) -> None: ...
    def export_database_csv(self) -> None: ...
    def normalize_stream_types(self) -> None: ...
    def cleanup_inactive_items(self) -> None: ...
    def save(self) -> None: ...
    def remove_mapping_rows(self) -> None: ...
    def fill_mapping_from_storage_paths(self) -> None: ...
    def save_mappings(self) -> None: ...
    def run_search(self) -> None: ...
    def export_search_csv(self) -> None: ...
    def save_current_search(self) -> None: ...
    def load_saved_search(self) -> None: ...
    def delete_saved_search(self) -> None: ...
    def run_sql(self) -> None: ...
    def save_current_sql(self) -> None: ...
    def load_saved_sql(self) -> None: ...
    def delete_saved_sql(self) -> None: ...
    def show_sql_help(self) -> None: ...
    def export_sql_help(self) -> None: ...
    def save_and_close(self) -> None: ...
    def add_mapping_row(self, mapping) -> None: ...


class MediaLibraryDialogView:
    """Erstellt und besitzt die Widgets des Dialogs."""

    def __init__(self, dialog: QDialog, actions: MediaLibraryDialogActions) -> None:
        self.dialog = dialog
        self.actions = actions
        self.scan_sensitive_widgets: list[QWidget] = []
        self.nfo_scan_sensitive_widgets: list[QWidget] = []
        self._build()

    def _build(self) -> None:
        root = QVBoxLayout(self.dialog)
        intro = QLabel(
            "Dragon Tools speichert eine eigene SQLite-Mediathek. Jellyfin-Datenbanken werden nur gelesen "
            "und in eine DragonTools-Datenbank importiert; Jellyfin selbst wird niemals verändert."
        )
        intro.setWordWrap(True)
        root.addWidget(intro)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_status_tab(), "Status / Import")
        self.tabs.addTab(self._build_mapping_tab(), "Pfad-Mapping")
        self.tabs.addTab(self._build_search_tab(), "Suchen")
        self.tabs.addTab(self._build_sql_tab(), "Bearbeiten")
        root.addWidget(self.tabs, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Close
        )
        save_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        if save_button:
            save_button.setText("Speichern")
            save_button.clicked.connect(self.actions.save)
        close_button = buttons.button(QDialogButtonBox.StandardButton.Close)
        if close_button:
            close_button.setText("Schließen")
        buttons.rejected.connect(self.actions.save_and_close)
        root.addWidget(buttons)

    def _build_status_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        config_group = QGroupBox("Datenbank")
        grid = QGridLayout(config_group)
        self.enabled_cb = QCheckBox("Mediathek-Datenbank verwenden")
        self.preflight_cb = QCheckBox("Preflight bevorzugt aus der Datenbank auflösen")
        self.analyze_import_cb = QCheckBox("Beim Import vorhandene Videodateien direkt analysieren (langsamer)")
        self.enabled_cb.toggled.connect(self.actions.update_enabled_state)
        grid.addWidget(self.enabled_cb, 0, 0, 1, 3)
        grid.addWidget(self.preflight_cb, 1, 0, 1, 3)
        grid.addWidget(self.analyze_import_cb, 2, 0, 1, 3)

        self.db_path_edit = QLineEdit()
        db_browse = QPushButton("...")
        db_browse.setFixedWidth(36)
        db_browse.clicked.connect(self.actions.browse_db_path)
        grid.addWidget(QLabel("DragonTools-DB:"), 3, 0)
        grid.addWidget(self.db_path_edit, 3, 1)
        grid.addWidget(db_browse, 3, 2)
        layout.addWidget(config_group)

        import_group = QGroupBox("Import / Export")
        import_layout = QGridLayout(import_group)
        self.jellyfin_path_edit = QLineEdit()
        jf_browse = QPushButton("...")
        jf_browse.setFixedWidth(36)
        jf_browse.clicked.connect(self.actions.browse_jellyfin_db)
        import_layout.addWidget(QLabel("Jellyfin-DB:"), 0, 0)
        import_layout.addWidget(self.jellyfin_path_edit, 0, 1)
        import_layout.addWidget(jf_browse, 0, 2)

        new_btn = QPushButton("Neue DB anlegen")
        new_btn.clicked.connect(self.actions.create_empty_database)
        import_btn = QPushButton("Jellyfin importieren")
        import_btn.clicked.connect(self.actions.import_jellyfin)
        scan_btn = QPushButton("Speicherpfade scannen")
        scan_btn.clicked.connect(self.actions.scan_storage_paths)
        scan_abort_btn = QPushButton("Scan abbrechen")
        scan_abort_btn.clicked.connect(self.actions.abort_storage_scan)
        scan_abort_btn.setEnabled(False)
        nfo_light_btn = QPushButton("NFO-Lightscan")
        nfo_light_btn.setToolTip("Prüft nur fehlende, unbekannte oder seit dem letzten Scan geänderte NFOs.")
        nfo_light_btn.clicked.connect(self.actions.scan_nfo_light)
        nfo_full_btn = QPushButton("NFO vollständig prüfen")
        nfo_full_btn.setToolTip("Liest alle bekannten NFOs neu ein und vergleicht sie mit der Mediathek-Datenbank.")
        nfo_full_btn.clicked.connect(self.actions.scan_nfo_full)
        nfo_abort_btn = QPushButton("NFO-Scan abbrechen")
        nfo_abort_btn.clicked.connect(self.actions.abort_nfo_scan)
        nfo_abort_btn.setEnabled(False)
        export_btn = QPushButton("DB exportieren")
        export_btn.clicked.connect(self.actions.export_database)
        export_csv_btn = QPushButton("DB als CSV exportieren")
        export_csv_btn.clicked.connect(self.actions.export_database_csv)
        normalize_btn = QPushButton("Streamtypen normalisieren")
        normalize_btn.clicked.connect(self.actions.normalize_stream_types)
        cleanup_btn = QPushButton("Inaktive Einträge bereinigen")
        cleanup_btn.clicked.connect(self.actions.cleanup_inactive_items)
        save_btn = QPushButton("Einstellungen speichern")
        save_btn.clicked.connect(self.actions.save)
        import_layout.addWidget(new_btn, 1, 0)
        import_layout.addWidget(import_btn, 1, 1)
        import_layout.addWidget(export_btn, 1, 2)
        import_layout.addWidget(scan_btn, 2, 0, 1, 2)
        import_layout.addWidget(scan_abort_btn, 2, 2)
        import_layout.addWidget(nfo_light_btn, 3, 0)
        import_layout.addWidget(nfo_full_btn, 3, 1)
        import_layout.addWidget(nfo_abort_btn, 3, 2)
        import_layout.addWidget(export_csv_btn, 4, 0, 1, 3)
        import_layout.addWidget(normalize_btn, 5, 0, 1, 3)
        import_layout.addWidget(cleanup_btn, 6, 0, 1, 3)
        import_layout.addWidget(save_btn, 7, 0, 1, 3)
        self.scan_progress = QProgressBar()
        self.scan_progress.setRange(0, 100)
        self.scan_progress.setValue(0)
        self.scan_status_label = QLabel(
            "Speicherpfad-Scan nutzt die hinterlegten Film-, Anime- und TV-Ordner. "
            "MediaInfo ist die primäre Analysequelle; ffprobe ergänzt fehlende Werte."
        )
        self.scan_status_label.setWordWrap(True)
        import_layout.addWidget(self.scan_progress, 8, 0, 1, 3)
        import_layout.addWidget(self.scan_status_label, 9, 0, 1, 3)
        self.nfo_progress = QProgressBar()
        self.nfo_progress.setRange(0, 100)
        self.nfo_progress.setValue(0)
        self.nfo_status_label = QLabel(
            "NFO-Lightscan arbeitet nur auf den bereits bekannten DB-Pfaden und startet keine Videoanalyse."
        )
        self.nfo_status_label.setWordWrap(True)
        import_layout.addWidget(self.nfo_progress, 10, 0, 1, 3)
        import_layout.addWidget(self.nfo_status_label, 11, 0, 1, 3)
        self.scan_btn = scan_btn
        self.scan_abort_btn = scan_abort_btn
        self.nfo_light_btn = nfo_light_btn
        self.nfo_full_btn = nfo_full_btn
        self.nfo_abort_btn = nfo_abort_btn
        self.scan_sensitive_widgets = [
            new_btn,
            import_btn,
            scan_btn,
            export_btn,
            export_csv_btn,
            normalize_btn,
            cleanup_btn,
            save_btn,
            nfo_light_btn,
            nfo_full_btn,
        ]
        self.nfo_scan_sensitive_widgets = [
            new_btn, import_btn, scan_btn, export_btn, export_csv_btn, normalize_btn,
            cleanup_btn, save_btn, nfo_light_btn, nfo_full_btn
        ]
        layout.addWidget(import_group)

        self.stats_label = QLabel("")
        self.stats_label.setWordWrap(True)
        self.stats_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.stats_label)
        layout.addStretch(1)
        return page

    def _build_mapping_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        hint = QLabel(
            "Pfad-Mapping übersetzt Jellyfin-Pfade in deine Windows-/NAS-Pfade, z. B. /Anime -> "
            "\\\\Medienserver\\video\\Serien\\Anime. Die Einträge sind frei anpassbar."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.mapping_table = QTableWidget(0, 3)
        self.mapping_table.setHorizontalHeaderLabels(["Bereich", "Jellyfin-Pfad", "DragonTools-Pfad"])
        self.mapping_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.mapping_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.mapping_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.mapping_table, 1)

        bar = QHBoxLayout()
        add_btn = QPushButton("Zeile hinzufügen")
        add_btn.clicked.connect(lambda: self.actions.add_mapping_row(None))
        remove_btn = QPushButton("Auswahl entfernen")
        remove_btn.clicked.connect(self.actions.remove_mapping_rows)
        defaults_btn = QPushButton("Aus Speicherpfaden ableiten")
        defaults_btn.clicked.connect(self.actions.fill_mapping_from_storage_paths)
        save_btn = QPushButton("Mapping speichern")
        save_btn.clicked.connect(self.actions.save_mappings)
        bar.addWidget(add_btn)
        bar.addWidget(remove_btn)
        bar.addWidget(defaults_btn)
        bar.addStretch(1)
        bar.addWidget(save_btn)
        layout.addLayout(bar)
        return page

    def _build_search_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)

        saved_bar = QHBoxLayout()
        saved_bar.addWidget(QLabel("Gespeicherte Suche:"))
        self.saved_search_combo = QComboBox()
        self.saved_search_combo.setMinimumWidth(240)
        saved_bar.addWidget(self.saved_search_combo, 1)
        load_saved_search_btn = QPushButton("Laden")
        load_saved_search_btn.clicked.connect(self.actions.load_saved_search)
        save_search_btn = QPushButton("Aktuelle speichern")
        save_search_btn.clicked.connect(self.actions.save_current_search)
        delete_search_btn = QPushButton("Löschen")
        delete_search_btn.clicked.connect(self.actions.delete_saved_search)
        saved_bar.addWidget(load_saved_search_btn)
        saved_bar.addWidget(save_search_btn)
        saved_bar.addWidget(delete_search_btn)
        layout.addLayout(saved_bar)

        top = QGridLayout()
        self.search_mode_combo = QComboBox()
        for label, key in SEARCH_MODES:
            self.search_mode_combo.addItem(label, key)
        self.search_mode_combo.currentIndexChanged.connect(self.update_search_options)

        self.search_option_combo = QComboBox()
        self.search_scope_combo = QComboBox()
        for label, key in SEARCH_SCOPES:
            self.search_scope_combo.addItem(label, key)
        self.search_type_combo = QComboBox()
        for label, key in SEARCH_ITEM_TYPES:
            self.search_type_combo.addItem(label, key)
        self.search_text_edit = QLineEdit()
        self.search_text_edit.setPlaceholderText("Optional: Titel, Serie, Dateiname oder Pfad")
        self.search_text_edit.returnPressed.connect(self.actions.run_search)
        search_btn = QPushButton("Suchen")
        search_btn.clicked.connect(self.actions.run_search)
        export_btn = QPushButton("Treffer als CSV")
        export_btn.clicked.connect(self.actions.export_search_csv)

        top.addWidget(QLabel("Abfrage:"), 0, 0)
        top.addWidget(self.search_mode_combo, 0, 1)
        top.addWidget(QLabel("Kriterium:"), 0, 2)
        top.addWidget(self.search_option_combo, 0, 3)
        top.addWidget(QLabel("Bereich:"), 1, 0)
        top.addWidget(self.search_scope_combo, 1, 1)
        top.addWidget(QLabel("Typ:"), 1, 2)
        top.addWidget(self.search_type_combo, 1, 3)
        top.addWidget(self.search_text_edit, 2, 0, 1, 4)
        top.addWidget(search_btn, 2, 4)
        top.addWidget(export_btn, 2, 5)
        top.setColumnStretch(3, 1)
        layout.addLayout(top)

        self.search_result_label = QLabel("0 Treffer")
        layout.addWidget(self.search_result_label)

        self.search_table = QTableWidget(0, 16)
        self.search_table.setHorizontalHeaderLabels(
            ["Typ", "Titel", "Serie", "S", "E", "Jahr", "Video", "Bild", "Audio", "Untertitel", "NFO", "NFO-Prüfung", "Dauer", "Größe", "Abweichung", "Pfad"]
        )
        header = self.search_table.horizontalHeader()
        for idx in range(15):
            header.setSectionResizeMode(idx, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(15, QHeaderView.ResizeMode.Stretch)
        self.search_table.setSortingEnabled(True)
        layout.addWidget(self.search_table, 1)
        self.update_search_options()
        return page

    def update_search_options(self, _index: int | None = None) -> None:
        mode = self.search_mode_combo.currentData() or "all"
        options = SEARCH_OPTIONS.get(str(mode), SEARCH_OPTIONS["all"])
        previous = self.search_option_combo.currentData()
        self.search_option_combo.blockSignals(True)
        self.search_option_combo.clear()
        for label, key in options:
            self.search_option_combo.addItem(label, key)
        if previous is not None:
            idx = self.search_option_combo.findData(previous)
            if idx >= 0:
                self.search_option_combo.setCurrentIndex(idx)
        self.search_option_combo.setEnabled(len(options) > 1)
        self.search_option_combo.blockSignals(False)

    def _build_sql_tab(self) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        warning = QLabel(
            "Manuelle SQL-Bearbeitung ist für gezielte Korrekturen gedacht. Vor Änderungen erstellt "
            "Dragon Tools automatisch eine Sicherung der eigenen Mediathek-Datenbank."
        )
        warning.setWordWrap(True)
        layout.addWidget(warning)

        saved_bar = QHBoxLayout()
        saved_bar.addWidget(QLabel("Gespeicherte SQL-Abfrage:"))
        self.saved_sql_combo = QComboBox()
        self.saved_sql_combo.setMinimumWidth(260)
        saved_bar.addWidget(self.saved_sql_combo, 1)
        load_sql_btn = QPushButton("Laden")
        load_sql_btn.clicked.connect(self.actions.load_saved_sql)
        save_sql_btn = QPushButton("Speichern")
        save_sql_btn.clicked.connect(self.actions.save_current_sql)
        delete_sql_btn = QPushButton("Löschen")
        delete_sql_btn.clicked.connect(self.actions.delete_saved_sql)
        saved_bar.addWidget(load_sql_btn)
        saved_bar.addWidget(save_sql_btn)
        saved_bar.addWidget(delete_sql_btn)
        layout.addLayout(saved_bar)

        self.sql_edit = QTextEdit()
        self.sql_edit.setPlaceholderText("SELECT * FROM media_items LIMIT 50")
        self.sql_edit.setPlainText(
            "SELECT item_type, title, series_title, season, episode, year, path FROM media_items LIMIT 50"
        )
        layout.addWidget(self.sql_edit, 1)

        bar = QHBoxLayout()
        help_btn = QPushButton("SQL-Hilfe / Tabellen & Attribute")
        help_btn.setToolTip("Zeigt verfügbare SQL-Befehle, alle Tabellen, Spalten und Beispielabfragen.")
        help_btn.clicked.connect(self.actions.show_sql_help)
        export_help_btn = QPushButton("Schema-Info exportieren")
        export_help_btn.clicked.connect(self.actions.export_sql_help)
        run_btn = QPushButton("SQL ausführen")
        run_btn.clicked.connect(self.actions.run_sql)
        bar.addWidget(help_btn)
        bar.addWidget(export_help_btn)
        bar.addStretch(1)
        bar.addWidget(run_btn)
        layout.addLayout(bar)

        self.sql_result_table = QTableWidget(0, 0)
        self.sql_result_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        layout.addWidget(self.sql_result_table, 2)
        return page

    def set_scan_running(self, running: bool) -> None:
        for widget in self.scan_sensitive_widgets:
            widget.setEnabled(not running)
        self.scan_abort_btn.setEnabled(running)

    def set_nfo_scan_running(self, running: bool) -> None:
        for widget in self.nfo_scan_sensitive_widgets:
            widget.setEnabled(not running)
        self.nfo_abort_btn.setEnabled(running)
