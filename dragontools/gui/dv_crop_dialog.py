# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from PyQt6.QtWidgets import QApplication, QMessageBox


def show_dv_crop_decision(worker, payload: object, *, log=None) -> None:
    data = dict(payload or {}) if isinstance(payload, dict) else {}
    request_id = str(data.get("request_id") or "")
    if not request_id:
        return
    box = QMessageBox(QApplication.activeWindow())
    box.setIcon(QMessageBox.Icon.Warning)
    box.setWindowTitle("Dolby Vision – Crop-Konflikt")
    name = Path(str(data.get("input_path") or "Datei")).name
    box.setText(
        f"Auto-Crop und Dolby-Vision-RPU weichen bei\n{name}\n"
        f"um {int(data.get('difference_px') or 0)} Pixel voneinander ab."
    )
    box.setInformativeText(
        f"Auto-Crop: {data.get('autocrop') or 'kein Crop'}\n"
        f"RPU Level 5: {data.get('rpu_crop') or 'kein Crop'}\n\n"
        "Wähle den Wert für den physischen Crop. 'Dolby Vision deaktivieren' "
        "plant die Datei danach automatisch ohne DV-Erhalt neu."
    )
    auto_btn = box.addButton("Auto-Crop verwenden", QMessageBox.ButtonRole.AcceptRole)
    rpu_btn = box.addButton("RPU-Wert verwenden", QMessageBox.ButtonRole.AcceptRole)
    box.addButton("Dolby Vision deaktivieren", QMessageBox.ButtonRole.DestructiveRole)
    box.exec()
    clicked = box.clickedButton()
    decision = "autocrop" if clicked is auto_btn else "rpu" if clicked is rpu_btn else "disable_dv"
    try:
        worker.provide_dv_crop_decision(request_id, decision)
    except (AttributeError, RuntimeError):
        if log:
            log("DV-Crop-Entscheidung konnte nicht an den Worker übergeben werden.", "error")
