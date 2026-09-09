# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from PyQt6.QtCore import QDate
from PyQt6.QtWidgets import QCheckBox, QDateEdit, QGridLayout, QGroupBox, QLabel, QLineEdit, QMessageBox, QPushButton
from ...core import settings as cfg
from ...core.paths import default_target_path_for_settings_key, ensure_default_storage_dirs
from ..info_button import InfoButton
from .base import SettingsSection


class StorageLoggingSection(SettingsSection):
    section_keys = ("paths", "logging", "log_cleanup")

    def build(self, vl) -> None:
        d = self.dialog
        # ── Zielpfade ──────────────────────────────────────────────
        paths_grp = QGroupBox("Zielpfade je Codec und Medientyp")
        d._section_widgets["paths"] = paths_grp
        pg = QGridLayout(paths_grp)
        pg.addWidget(QLabel(
            "Standardordner werden automatisch unter Dokumente\\DragonTools\\Ausgabe angelegt.\n"
            "Du kannst die Pfade bei Bedarf überschreiben; leere Felder fallen auf den Standard zurück."
        ), 0, 0, 1, 4)

        d._path_edits: dict[str, QLineEdit] = {}
        row = 1
        for codec, keys, desc in (
            ("H.264", (cfg.SET_KEY_PATH_H264_TV, cfg.SET_KEY_PATH_H264_ANIME, cfg.SET_KEY_PATH_H264_FILME),
             "H.264-Ausgabe (ältere Geräte bis ca. 2015)"),
            ("H.265", (cfg.SET_KEY_PATH_H265_TV, cfg.SET_KEY_PATH_H265_ANIME, cfg.SET_KEY_PATH_H265_FILME),
             "H.265 / HEVC-Ausgabe (moderne Geräte ab 2015)"),
            ("AV1",   (cfg.SET_KEY_PATH_AV1_TV,  cfg.SET_KEY_PATH_AV1_ANIME,  cfg.SET_KEY_PATH_AV1_FILME),
             "AV1-Ausgabe (sehr moderne Geräte ab ca. 2023)"),
        ):
            pg.addWidget(QLabel(f"<b>{codec}</b> – {desc}"), row, 0, 1, 4); row += 1
            for lbl, key, info in zip(
                ("TV:", "Anime:", "Film:"), keys,
                (f"TV-Serien-Ordner für {codec} (SxxExx wird automatisch sortiert).",
                 f"Anime-Serien-Ordner für {codec}.",
                 f"Filme-Ordner für {codec}.")
            ):
                ed = QLineEdit(); d._path_edits[key] = ed
                ed.setPlaceholderText(default_target_path_for_settings_key(key, create=False))
                d.row(pg, row, lbl, ed, info,
                          browse_fn=lambda _, e=ed: d.browse(e))
                row += 1
        vl.addWidget(paths_grp)

        # ── Aktiv-Flags ────────────────────────────────────────────
        # Medientypen-Checkboxen: nicht angezeigt, für _load/_save behalten
        d.cb_tv    = QCheckBox("TV");    d.cb_tv.setChecked(True)
        d.cb_anime = QCheckBox("Anime"); d.cb_anime.setChecked(True)
        d.cb_filme = QCheckBox("Filme"); d.cb_filme.setChecked(True)
        # ── Logging ────────────────────────────────────────────────
        log_grp = QGroupBox("Logging")
        d._section_widgets["logging"] = log_grp
        lg = QGridLayout(log_grp)
        lg.addWidget(QLabel(
            "Logs werden mit Jahr/Monat-Struktur gespeichert:\n"
            "LogOrdner\\Logging\\2025\\08-August\\dd.mm.yyyy_HH-MM.txt\n"
            "Die Einstellungen gelten für alle Codecs."
        ), 0, 0, 1, 4)

        d._log_edits: dict[str, QLineEdit] = {}
        d._log_cbs:   dict[str, QCheckBox] = {}

        _cb_log = QCheckBox("Logging aktiv")
        _cb_log.setChecked(True)
        d._log_cbs[cfg.SET_KEY_LOG_ENABLED] = _cb_log
        lg.addWidget(_cb_log, 1, 0)
        lg.addWidget(InfoButton(
            "Logging aktivieren. Logs enthalten alle Entscheidungen "
            "(Audio, Untertitel, Pipeline, Dateigroessen)."
        ), 1, 1)
        _ed_log = QLineEdit()
        d._log_edits[cfg.SET_KEY_LOG_ROOT] = _ed_log
        d.row(lg, 2, "Logging-Ordner:", _ed_log,
                  "Log-Ordner. Leer = Dokumente/DragonTools/Logging.",
                  browse_fn=lambda _, e=_ed_log: d.browse(e))
        vl.addWidget(log_grp)

        # ── Log-Bereinigung ─────────────────────────────────────────
        cleanup_grp = QGroupBox("Log-Bereinigung")
        d._section_widgets["log_cleanup"] = cleanup_grp
        clg = QGridLayout(cleanup_grp)
        cleanup_desc = QLabel(
            "Löscht normale Logs, ErrorReports, CrashReports und VerboseLogs im "
            "konfigurierten DragonTools-Logbereich. Der aktive Crash-Marker bleibt erhalten."
        )
        cleanup_desc.setWordWrap(True)
        clg.addWidget(cleanup_desc, 0, 0, 1, 4)
        clg.addWidget(QLabel("Bis Datum:"), 1, 0)
        d.log_cleanup_date_edit = QDateEdit()
        d.log_cleanup_date_edit.setCalendarPopup(True)
        d.log_cleanup_date_edit.setDisplayFormat("dd.MM.yyyy")
        d.log_cleanup_date_edit.setDate(QDate.currentDate().addMonths(-1))
        clg.addWidget(d.log_cleanup_date_edit, 1, 1)
        clg.addWidget(InfoButton(
            "Löscht nur Logdateien, deren Änderungsdatum am oder vor diesem Datum liegt."
        ), 1, 2)
        d.cleanup_normal_cb = QCheckBox("Normale Logs")
        d.cleanup_error_cb = QCheckBox("ErrorReports")
        d.cleanup_crash_cb = QCheckBox("CrashReports")
        d.cleanup_verbose_cb = QCheckBox("VerboseLogs")
        for cb in (
            d.cleanup_normal_cb,
            d.cleanup_error_cb,
            d.cleanup_crash_cb,
            d.cleanup_verbose_cb,
        ):
            cb.setChecked(True)
        clg.addWidget(QLabel("Logarten:"), 2, 0)
        clg.addWidget(d.cleanup_normal_cb, 2, 1)
        clg.addWidget(d.cleanup_error_cb, 2, 2)
        clg.addWidget(d.cleanup_crash_cb, 3, 1)
        clg.addWidget(d.cleanup_verbose_cb, 3, 2)
        clg.addWidget(InfoButton(
            "Alle Logarten sind standardmäßig aktiv. Du kannst gezielt nur normale Logs, ErrorReports, CrashReports oder VerboseLogs löschen."
        ), 2, 3, 2, 1)
        cleanup_until_btn = QPushButton("Logs bis Datum löschen")
        cleanup_until_btn.clicked.connect(lambda: d.cleanup_logs(all_logs=False))
        clg.addWidget(cleanup_until_btn, 4, 0, 1, 2)
        cleanup_all_btn = QPushButton("Alle Logs löschen")
        cleanup_all_btn.clicked.connect(lambda: d.cleanup_logs(all_logs=True))
        clg.addWidget(cleanup_all_btn, 4, 2, 1, 1)
        clg.addWidget(InfoButton(
            "Alle ausgewählten Logarten im DragonTools-Logbereich löschen. "
            "Diese Aktion hat eine Sicherheitsabfrage."
        ), 4, 3)
        vl.addWidget(cleanup_grp)


    def load(self) -> None:
        d, s = self.dialog, self.settings
        try:
            ensure_default_storage_dirs()
        except OSError as exc:
            QMessageBox.warning(
                d,
                "Standardordner nicht anlegbar",
                "Die Standard-Speicherordner unter Dokumente\\DragonTools\\Ausgabe "
                f"konnten nicht angelegt werden.\n\n{exc}",
            )
        for key, ed in d._path_edits.items():
            default_path = default_target_path_for_settings_key(key, create=False)
            value = s.value(key, "", type=str).strip()
            ed.setPlaceholderText(default_path)
            ed.setText(value or default_path)
        d.cb_tv.setChecked(s.value(cfg.SET_KEY_ACTIVE_ALL_TV, True, type=bool))
        d.cb_anime.setChecked(s.value(cfg.SET_KEY_ACTIVE_ALL_ANIME, True, type=bool))
        d.cb_filme.setChecked(s.value(cfg.SET_KEY_ACTIVE_ALL_FILME, True, type=bool))

        enabled = True
        for key in cfg.LOG_ENABLED_KEYS:
            if s.contains(key):
                enabled = s.value(key, True, type=bool)
                break
        d._log_cbs[cfg.SET_KEY_LOG_ENABLED].setChecked(enabled)

        log_root = ""
        for key in cfg.LOG_ROOT_KEYS:
            value = s.value(key, "", type=str)
            if value and value.strip():
                log_root = value.strip()
                break
        d._log_edits[cfg.SET_KEY_LOG_ROOT].setText(log_root)

    def save(self) -> bool:
        d, s = self.dialog, self.settings
        for key, ed in d._path_edits.items():
            value = ed.text().strip() or default_target_path_for_settings_key(key)
            try:
                Path(value).mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                QMessageBox.warning(
                    d,
                    "Zielpfad nicht anlegbar",
                    f"Der Zielpfad kann nicht angelegt werden:\n{value}\n\n{exc}",
                )
                return False
            s.setValue(key, value)
        s.setValue(cfg.SET_KEY_ACTIVE_ALL_TV, d.cb_tv.isChecked())
        s.setValue(cfg.SET_KEY_ACTIVE_ALL_ANIME, d.cb_anime.isChecked())
        s.setValue(cfg.SET_KEY_ACTIVE_ALL_FILME, d.cb_filme.isChecked())

        log_enabled = d._log_cbs[cfg.SET_KEY_LOG_ENABLED].isChecked()
        log_root = d._log_edits[cfg.SET_KEY_LOG_ROOT].text().strip()
        for key in cfg.LOG_ENABLED_KEYS:
            s.setValue(key, log_enabled)
        for key in cfg.LOG_ROOT_KEYS:
            s.setValue(key, log_root)
        return True

    def cleanup_logs(self, *, all_logs: bool) -> None:
        d = self.dialog
        from ...core.log_cleanup import (
            LOG_CATEGORY_CRASH,
            LOG_CATEGORY_ERROR,
            LOG_CATEGORY_NORMAL,
            LOG_CATEGORY_VERBOSE,
            cleanup_logs,
        )

        categories: list[str] = []
        if d.cleanup_normal_cb.isChecked():
            categories.append(LOG_CATEGORY_NORMAL)
        if d.cleanup_error_cb.isChecked():
            categories.append(LOG_CATEGORY_ERROR)
        if d.cleanup_crash_cb.isChecked():
            categories.append(LOG_CATEGORY_CRASH)
        if d.cleanup_verbose_cb.isChecked():
            categories.append(LOG_CATEGORY_VERBOSE)
        if not categories:
            QMessageBox.information(d, "Keine Logart gewählt", "Bitte wähle mindestens eine Logart aus.")
            return

        log_root = d._log_edits[cfg.SET_KEY_LOG_ROOT].text().strip()
        if not log_root:
            log_root = str(Path.home() / "Documents" / "DragonTools")
        labels = {
            LOG_CATEGORY_NORMAL: "normale Logs",
            LOG_CATEGORY_ERROR: "ErrorReports",
            LOG_CATEGORY_CRASH: "CrashReports",
            LOG_CATEGORY_VERBOSE: "VerboseLogs",
        }
        category_label = ", ".join(labels[category] for category in categories)

        if all_logs:
            cutoff = None
            question = (
                "Alle ausgewählten DragonTools-Logs im konfigurierten Logbereich löschen?\n\n"
                f"Logarten: {category_label}\n{log_root}"
            )
        else:
            qdate = d.log_cleanup_date_edit.date()
            cutoff = qdate.toPyDate()
            question = (
                "DragonTools-Logs bis einschließlich dieses Datum löschen?\n\n"
                f"Datum: {qdate.toString('dd.MM.yyyy')}\n"
                f"Logarten: {category_label}\nLogbereich: {log_root}"
            )
        answer = QMessageBox.question(
            d,
            "Log-Bereinigung bestätigen",
            question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = cleanup_logs(log_root, cutoff_date=cutoff, categories=categories)
        except (OSError, ValueError) as exc:
            QMessageBox.critical(d, "Log-Bereinigung fehlgeschlagen", str(exc))
            return
        QMessageBox.information(
            d,
            "Log-Bereinigung abgeschlossen",
            "Bereinigung abgeschlossen.\n\n"
            f"Gelöschte Dateien: {result.deleted_files}\n"
            f"Gelöschte Ordner: {result.deleted_dirs}\n"
            f"Übersprungene Dateien: {result.skipped_files}",
        )
