# -*- coding: utf-8 -*-
from __future__ import annotations

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QMessageBox, QTableWidgetItem

from .quality_tester_run_dialog import _QualityRunDialog


class QualityTesterRunConfigMixin:
    def _add_default_runs(self) -> None:
        self._add_run_row({
            "active": "ja",
            "name": "H265 CPU CRF23",
            "codec": "h265",
            "encoder": "cpu",
            "quality": 23,
            "preset": "medium",
            "pix_fmt": "10-bit",
            "scale": "original",
            "extra_args": "",
            "encoder_options": {
                "encoder": "cpu",
                "tune": "none",
                "aq_mode": "2",
                "aq_strength": 1.0,
                "psy_rd": 2.0,
                "psy_rdoq": 1.0,
                "bf": 8,
                "rc_lookahead": 40,
            },
        })
        self._add_run_row({
            "active": "ja",
            "name": "H265 NVENC CQ23",
            "codec": "h265",
            "encoder": "nvenc",
            "quality": 23,
            "preset": "p6",
            "pix_fmt": "10-bit",
            "scale": "original",
            "extra_args": "",
            "encoder_options": {
                "encoder": "nvenc",
                "preset": "p6",
                "cq": 23,
                "bf": 4,
                "rc_lookahead": 32,
                "aq_strength": 8,
                "bref_mode": "middle",
                "spatial_aq": True,
                "temporal_aq": True,
            },
        })

    def _make_item(self, text: str, *, checkable: bool = False, checked: bool = True) -> QTableWidgetItem:
        item = QTableWidgetItem(text)
        if checkable:
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
        return item

    def _row_dict_from_values(self, values: list[str] | dict | None = None) -> dict:
        if isinstance(values, dict):
            return dict(values)
        vals = values or ["ja", "Neuer Testlauf", "h265", "cpu", "23", "medium", "10-bit", "original", ""]
        return {
            "active": vals[0] if len(vals) > 0 else "ja",
            "name": vals[1] if len(vals) > 1 else "Neuer Testlauf",
            "codec": vals[2] if len(vals) > 2 else "h265",
            "encoder": vals[3] if len(vals) > 3 else "cpu",
            "quality": vals[4] if len(vals) > 4 else "23",
            "preset": vals[5] if len(vals) > 5 else "medium",
            "pix_fmt": vals[6] if len(vals) > 6 else "10-bit",
            "scale": vals[7] if len(vals) > 7 else "original",
            "extra_args": vals[8] if len(vals) > 8 else "",
            "encoder_options": {},
        }

    def _add_run_row(self, values: list[str] | dict | None = None) -> None:
        if self.run_table.rowCount() >= 20:
            QMessageBox.information(self, "Testläufe", "Maximal 20 Testläufe sind vorgesehen.")
            return
        vals = self._row_dict_from_values(values)
        row = self.run_table.rowCount()
        self.run_table.insertRow(row)
        self.run_table.setItem(
            row,
            self.RUN_COL_ACTIVE,
            self._make_item("", checkable=True, checked=str(vals.get("active", "ja")).lower() != "nein"),
        )
        ordered = [
            ("name", "Neuer Testlauf"),
            ("codec", "h265"),
            ("encoder", "cpu"),
            ("quality", "23"),
            ("preset", "medium"),
            ("pix_fmt", "10-bit"),
            ("scale", "original"),
            ("extra_args", ""),
        ]
        for col, (key, default) in enumerate(ordered, start=1):
            item = self._make_item(str(vals.get(key, default)))
            if col == self.RUN_COL_NAME:
                item.setData(Qt.ItemDataRole.UserRole, dict(vals.get("encoder_options") or {}))
            self.run_table.setItem(row, col, item)

    def _add_run_dialog(self) -> None:
        dlg = _QualityRunDialog(parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._add_run_row(dlg.values())

    def _row_to_dict(self, row: int) -> dict:
        def _cell(col: int, default: str = "") -> str:
            item = self.run_table.item(row, col)
            return item.text().strip() if item else default

        active_item = self.run_table.item(row, self.RUN_COL_ACTIVE)
        name_item = self.run_table.item(row, self.RUN_COL_NAME)
        encoder_options = name_item.data(Qt.ItemDataRole.UserRole) if name_item else {}
        data = {
            "active": "ja" if active_item and active_item.checkState() == Qt.CheckState.Checked else "nein",
            "name": _cell(self.RUN_COL_NAME, f"Testlauf {row + 1}"),
            "codec": _cell(self.RUN_COL_CODEC, "h265"),
            "encoder": _cell(self.RUN_COL_ENCODER, "cpu"),
            "quality": _cell(self.RUN_COL_QUALITY, "23"),
            "preset": _cell(self.RUN_COL_PRESET, "medium"),
            "pix_fmt": _cell(self.RUN_COL_PIXFMT, "10-bit"),
            "scale": _cell(self.RUN_COL_SCALE, "original"),
            "extra_args": _cell(self.RUN_COL_EXTRA, ""),
            "encoder_options": dict(encoder_options) if isinstance(encoder_options, dict) else {},
        }
        encoder = str(data["encoder"]).lower()
        preset = str(data["preset"] or "medium")
        try:
            quality = max(0, min(63, int(data["quality"])))
        except Exception:
            quality = 23
        opts = dict(data["encoder_options"] or {})
        if opts.get("encoder") not in {encoder, None}:
            opts = {}
        opts["encoder"] = encoder
        opts["preset"] = preset
        if encoder == "nvenc":
            opts["cq"] = quality
        elif encoder == "qsv":
            opts["q"] = quality
        elif encoder == "amf":
            opts["qp"] = quality
            opts["quality"] = preset
        data["encoder_options"] = opts
        return data

    def _edit_run_row(self, row: int) -> None:
        if row < 0 or row >= self.run_table.rowCount():
            return
        current = self._row_to_dict(row)
        dlg = _QualityRunDialog(current, parent=self)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        updated = dlg.values()
        updated["active"] = current.get("active", "ja")
        active_item = self.run_table.item(row, self.RUN_COL_ACTIVE)
        checked = active_item.checkState() == Qt.CheckState.Checked if active_item else True
        self.run_table.setItem(row, self.RUN_COL_ACTIVE, self._make_item("", checkable=True, checked=checked))
        for col, key in (
            (self.RUN_COL_NAME, "name"),
            (self.RUN_COL_CODEC, "codec"),
            (self.RUN_COL_ENCODER, "encoder"),
            (self.RUN_COL_QUALITY, "quality"),
            (self.RUN_COL_PRESET, "preset"),
            (self.RUN_COL_PIXFMT, "pix_fmt"),
            (self.RUN_COL_SCALE, "scale"),
            (self.RUN_COL_EXTRA, "extra_args"),
        ):
            item = self._make_item(str(updated.get(key, "")))
            if col == self.RUN_COL_NAME:
                item.setData(Qt.ItemDataRole.UserRole, dict(updated.get("encoder_options") or {}))
            self.run_table.setItem(row, col, item)

    def _remove_selected_runs(self) -> None:
        rows = sorted({idx.row() for idx in self.run_table.selectedIndexes()}, reverse=True)
        for row in rows:
            self.run_table.removeRow(row)
