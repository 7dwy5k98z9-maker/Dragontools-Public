# -*- coding: utf-8 -*-
"""Benutzerentscheidungs-Dialoge für MoveThread-Anfragen."""
from __future__ import annotations

import traceback
from pathlib import Path
from PyQt6.QtCore import Qt, QSettings, QTimer
from PyQt6.QtWidgets import (QDialog, QDialogButtonBox, QGroupBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QRadioButton, QVBoxLayout)
from ..rules.move_rules import default_film_series_name, normalize_relative_move_subpath, resolve_film_target_for_path
from .ui_helpers import install_persistent_window_geometry


class MoveRequestDialogHandler:
    def __init__(self, *, state, log, parent):
        self._state = state
        self._log = log
        self._parent = parent

    def on_move_req(self, rid: str, payload: dict) -> None:
            """Slot für move_thread.request_user – dispatcht nach Anfrage-Typ."""
            try:
                req_type = payload.get("type", "")
                if req_type == "choose_series_base_or_folder":
                    self.handle_series_base_or_folder(rid, payload)
                elif req_type == "choose_series_folder":
                    self.handle_series_folder(rid, payload)
                elif req_type == "film_destination":
                    self.film_destination_dialog(rid, payload)
                elif req_type == "confirm_shutdown_with_countdown":
                    self.handle_shutdown_countdown(rid, payload)
                else:
                    self._state.move_thread.provide_decision(rid, {"abort": True})
            except Exception:
                self._log("\u274c Unbehandelte Ausnahme in on_move_req()", "error")
                self._log(traceback.format_exc(), "error")
                try:
                    if self._state.move_thread:
                        self._state.move_thread.provide_decision(rid, {"abort": True})
                except Exception:
                    pass

    def film_destination_dialog(self, rid: str, payload: dict) -> None:
            stem         = payload.get("stem", "Film")
            similar_files = payload.get("similar_files", [])

            dlg = QDialog(self._parent)
            dlg.setWindowTitle(f"Film verschieben: {stem}")
            dlg.setMinimumWidth(500)
            install_persistent_window_geometry(dlg, "move_film_destination_dialog")
            layout = QVBoxLayout(dlg)
            layout.addWidget(QLabel(f"<b>{stem}</b>"))
            layout.addWidget(QLabel("Einzelfilm oder Teil einer Filmreihe?"))

            rb_single = QRadioButton("\U0001F3AC Einzelfilm  (Filme/{Buchstabe}/{Filmname}/)")
            rb_series = QRadioButton("\U0001F4DA Filmreihe  (Filme/{Buchstabe}/{Reihenname}/{Filmname}/)")
            rb_single.setChecked(True)
            layout.addWidget(rb_single)
            layout.addWidget(rb_series)

            series_group  = QGroupBox("Name der Filmreihe")
            series_layout = QVBoxLayout(series_group)
            series_edit   = QLineEdit(default_film_series_name(stem))
            series_layout.addWidget(series_edit)
            series_layout.addWidget(QLabel("Unterordner / Unterebene optional"))
            subpath_edit  = QLineEdit()
            subpath_edit.setPlaceholderText(
                "relativ, z. B. Trilogie oder Spider-Verse/Miles Morales"
            )
            series_layout.addWidget(subpath_edit)
            series_group.setVisible(False)
            rb_series.toggled.connect(series_group.setVisible)
            layout.addWidget(series_group)

            similar_list = None
            if similar_files:
                similar_group  = QGroupBox(
                    f"Weitere Dateien in der Liste ({len(similar_files)}) \u2013 ebenfalls als Reihe verschieben?"
                )
                similar_layout = QVBoxLayout(similar_group)
                similar_list   = QListWidget()
                similar_list.setMaximumHeight(120)
                for file_path in similar_files:
                    item = QListWidgetItem(Path(file_path).name)
                    item.setData(Qt.ItemDataRole.UserRole, file_path)
                    item.setCheckState(Qt.CheckState.Checked)
                    similar_list.addItem(item)
                similar_layout.addWidget(similar_list)
                layout.addWidget(similar_group)

            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
            )

            def _accept_dialog() -> None:
                if not rb_series.isChecked():
                    dlg.accept()
                    return
                try:
                    normalize_relative_move_subpath(subpath_edit.text())
                except ValueError as exc:
                    QMessageBox.warning(dlg, "Ungueltiger Unterordner", str(exc))
                    return
                dlg.accept()

            buttons.accepted.connect(_accept_dialog)
            buttons.rejected.connect(dlg.reject)
            layout.addWidget(buttons)

            if dlg.exec() != QDialog.DialogCode.Accepted:
                self._state.move_thread.provide_decision(rid, {"abort": True})
                return

            mode             = "series" if rb_series.isChecked() else "single"
            series_name      = series_edit.text().strip() or stem
            relative_subpath = normalize_relative_move_subpath(subpath_edit.text()) if mode == "series" else ""
            response = {
                "mode": mode,
                "series_name": series_name,
                "relative_subpath": relative_subpath,
            }

            if similar_list and mode == "series":
                filme_path = payload.get("filme_path", "")
                for index in range(similar_list.count()):
                    item = similar_list.item(index)
                    if item.checkState() == Qt.CheckState.Checked:
                        file_path = item.data(Qt.ItemDataRole.UserRole)
                        if file_path and file_path not in self._state.planned_targets:
                            target_dir = resolve_film_target_for_path(
                                file_path,
                                base_path=filme_path,
                                series_name=series_name,
                                mode="series",
                                relative_subpath=relative_subpath,
                            )
                            if not target_dir:
                                continue
                            planned_target = (
                                {"target": target_dir, "subpath": relative_subpath}
                                if relative_subpath else target_dir
                            )
                            self._state.planned_targets[file_path] = planned_target
                            if self._state.move_thread and self._state.move_thread.isRunning():
                                self._state.move_thread.add_planned_target(file_path, planned_target)

            self._state.move_thread.provide_decision(rid, response)

    def handle_series_base_or_folder(self, rid: str, payload: dict) -> None:
            bases = [base for base in (payload.get("bases") or []) if base]
            if not bases:
                self._state.move_thread.provide_decision(rid, {"abort": True})
                return
            label, ok = QInputDialog.getItem(
                self._parent,
                "Serientyp",
                f"Wohin mit '{payload.get('series_name', '')}'?",
                [base["label"] for base in bases],
                editable=False,
            )
            if not ok:
                self._state.move_thread.provide_decision(rid, {"abort": True})
                return
            base = next(base for base in bases if base["label"] == label)
            self._state.move_thread.provide_decision(
                rid,
                {"base_path": base["path"], "folder_name": payload.get("series_name", "")},
            )

    def handle_series_folder(self, rid: str, payload: dict) -> None:
            candidates = payload.get("candidates", [])
            label, ok = QInputDialog.getItem(
                self._parent,
                "Serienordner",
                "Zielordner:",
                [candidate["label"] for candidate in candidates],
                editable=False,
            )
            if not ok:
                self._state.move_thread.provide_decision(rid, {"abort": True})
                return
            selected = next(candidate for candidate in candidates if candidate["label"] == label)
            self._state.move_thread.provide_decision(rid, {"path": selected["path"]})

    def handle_shutdown_countdown(self, rid: str, payload: dict) -> None:
            try:
                from ..core.settings import APP_ORG, APP_NAME, SET_KEY_SHUTDOWN_COUNTDOWN
                _s = QSettings(APP_ORG, APP_NAME)
                countdown_secs = int(_s.value(SET_KEY_SHUTDOWN_COUNTDOWN, 30, type=int))
                countdown_secs = max(5, countdown_secs)
            except Exception:
                countdown_secs = 30

            dlg_shut = QDialog(self._parent)
            dlg_shut.setWindowTitle("Herunterfahren")
            dlg_shut.setMinimumWidth(360)
            dlg_shut.setWindowFlag(Qt.WindowType.WindowCloseButtonHint, False)
            install_persistent_window_geometry(dlg_shut, "shutdown_countdown_dialog")
            _lay = QVBoxLayout(dlg_shut)
            _countdown_lbl = QLabel()
            _countdown_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            _countdown_lbl.setStyleSheet("font-size:14px; padding:12px;")
            _lay.addWidget(_countdown_lbl)

            _btn_row = QHBoxLayout()
            _btn_yes = QPushButton("\u2705 Jetzt herunterfahren")
            _btn_no  = QPushButton("\u274c Abbrechen")
            _btn_row.addWidget(_btn_yes)
            _btn_row.addWidget(_btn_no)
            _lay.addLayout(_btn_row)

            _remaining = [countdown_secs]

            def _update_label() -> None:
                _countdown_lbl.setText(
                    f"PC herunterfahren?"
                    f"<br><br>"
                    f"<b style='font-size:22px;'>{_remaining[0]}</b>"
                    f"<br><span style='color:#64748b;font-size:12px;'>"
                    f"Sekunden bis automatisches Herunterfahren</span>"
                )
                _countdown_lbl.setTextFormat(Qt.TextFormat.RichText)

            def _tick() -> None:
                _remaining[0] -= 1
                _update_label()
                if _remaining[0] <= 0:
                    _timer.stop()
                    dlg_shut.accept()

            _btn_yes.clicked.connect(lambda: (_timer.stop(), dlg_shut.accept()))
            _btn_no.clicked.connect(lambda:  (_timer.stop(), dlg_shut.reject()))

            _update_label()
            _timer = QTimer(dlg_shut)
            _timer.setInterval(1000)
            _timer.timeout.connect(_tick)
            _timer.start()

            user_confirmed = dlg_shut.exec() == QDialog.DialogCode.Accepted
            self._state.move_thread.provide_decision(rid, {"ok": user_confirmed})
