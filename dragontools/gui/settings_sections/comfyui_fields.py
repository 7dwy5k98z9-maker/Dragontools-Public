# -*- coding: utf-8 -*-
"""ComfyUI/HDRTVDM controls for the video settings section."""
from __future__ import annotations

from pathlib import Path

from PyQt6.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QGridLayout, QHBoxLayout, QLabel,
    QLineEdit, QPushButton, QSpinBox,
)

from ...core import settings as cfg
from ...core.comfyui_hdr_models import CUSTOM_PROFILE, HDRTVDM_PROFILE
from ..info_button import InfoButton


def _browse_start_file(dialog) -> None:
    current = dialog.comfyui_start_file_edit.text().strip()
    start_dir = str(Path(current).parent) if current else ""
    path, _ = QFileDialog.getOpenFileName(
        dialog,
        "ComfyUI-Startdatei wählen",
        start_dir,
        "ComfyUI-Launcher (*.bat *.cmd *.exe);;Alle Dateien (*.*)",
    )
    if path:
        dialog.comfyui_start_file_edit.setText(path)


def build_comfyui_fields(dialog, grid: QGridLayout) -> int:
    grid.addWidget(QLabel("ComfyUI API:"), 2, 0)
    dialog.comfyui_base_url_edit = QLineEdit()
    dialog.comfyui_base_url_edit.setPlaceholderText(cfg.DEFAULT_COMFYUI_BASE_URL)
    grid.addWidget(dialog.comfyui_base_url_edit, 2, 1)
    grid.addWidget(InfoButton(
        "Lokale ComfyUI-Serveradresse. Standard: http://127.0.0.1:8188. DragonTools nutzt den HTTP-API-Vertrag."
    ), 2, 2)

    dialog.comfyui_auto_start_cb = QCheckBox("ComfyUI bei Bedarf automatisch starten")
    grid.addWidget(dialog.comfyui_auto_start_cb, 3, 0, 1, 2)
    grid.addWidget(InfoButton(
        "Wenn die API beim Start eines SDR→HDR-Jobs nicht erreichbar ist, startet DragonTools die konfigurierte "
        "Startdatei genau einmal und wartet anschließend bis zur eingestellten Frist auf die API. Ist ComfyUI bereits "
        "erreichbar, wird kein weiterer Prozess gestartet."
    ), 3, 2)

    grid.addWidget(QLabel("ComfyUI Startdatei:"), 4, 0)
    start_row = QHBoxLayout()
    dialog.comfyui_start_file_edit = QLineEdit()
    dialog.comfyui_start_file_edit.setPlaceholderText(r"z. B. C:\ComfyUI_windows_portable\run_nvidia_gpu.bat")
    start_row.addWidget(dialog.comfyui_start_file_edit, 1)
    browse = QPushButton("…")
    browse.setFixedWidth(34)
    browse.clicked.connect(lambda: _browse_start_file(dialog))
    start_row.addWidget(browse)
    grid.addLayout(start_row, 4, 1)
    grid.addWidget(InfoButton(
        "Für ComfyUI Portable am besten die vorhandene run_nvidia_gpu.bat (oder eine eigene .bat/.cmd/.exe) wählen. "
        "main.py allein ist keine vollständige Startdatei, weil dafür zusätzlich der passende Python-Interpreter und "
        "Startparameter nötig wären."
    ), 4, 2)

    grid.addWidget(QLabel("Start-Wartezeit:"), 5, 0)
    dialog.comfyui_start_wait_spin = QSpinBox()
    dialog.comfyui_start_wait_spin.setRange(5, 180)
    dialog.comfyui_start_wait_spin.setSuffix(" s")
    grid.addWidget(dialog.comfyui_start_wait_spin, 5, 1)
    grid.addWidget(InfoButton(
        "DragonTools prüft während dieser Zeit wiederholt die ComfyUI-API. Standard: 30 Sekunden."
    ), 5, 2)

    grid.addWidget(QLabel("AI-HDR-Modell:"), 6, 0)
    dialog.comfyui_model_profile_combo = QComboBox()
    dialog.comfyui_model_profile_combo.addItem("HDRTVDM LSN / params_3DM.pth (empfohlen)", HDRTVDM_PROFILE)
    dialog.comfyui_model_profile_combo.addItem("Benutzerdefiniert / später", CUSTOM_PROFILE)
    grid.addWidget(dialog.comfyui_model_profile_combo, 6, 1)
    grid.addWidget(InfoButton(
        "Für RTX 4080 16 GB ist HDRTVDM das ausführbare Startprofil: SDR BT.709 → PQ/BT.2020. "
        "DragonTools erwartet das offizielle Repository und bevorzugt method/params_3DM.pth. "
        "Der Checkpoint beeinflusst den HDR-Look deutlich stärker als fp16/fp32 oder die Batchgröße."
    ), 6, 2)

    grid.addWidget(QLabel("HDRTVDM Repository:"), 7, 0)
    dialog.comfyui_model_root_edit = QLineEdit()
    dialog.comfyui_model_root_edit.setPlaceholderText(r"z. B. C:\AI\HDRTVDM")
    grid.addWidget(dialog.comfyui_model_root_edit, 7, 1)
    grid.addWidget(InfoButton(
        "Ordner des offiziellen AndreGuo/HDRTVDM-Repositories; method/network.py muss vorhanden sein."
    ), 7, 2)

    grid.addWidget(QLabel("HDRTVDM Checkpoint:"), 8, 0)
    dialog.comfyui_checkpoint_edit = QLineEdit()
    dialog.comfyui_checkpoint_edit.setPlaceholderText("leer = method/params_3DM.pth, danach params.pth")
    grid.addWidget(dialog.comfyui_checkpoint_edit, 8, 1)
    grid.addWidget(InfoButton(
        "Empfohlen: method/params_3DM.pth (HDRTV4K / 3 Degradation Models, Paper-Look). "
        "Alternativ: params.pth (HDRTV1K/YouTube-DM) oder params_DaVinci.pth (DaVinci-DM). "
        "Ein expliziter Pfad überschreibt die automatische Auswahl."
    ), 8, 2)

    grid.addWidget(QLabel("ComfyUI Workflow (API-JSON):"), 9, 0)
    dialog.comfyui_workflow_path_edit = QLineEdit()
    dialog.comfyui_workflow_path_edit.setPlaceholderText("leer = eingebautes HDRTVDM-Workflow-Template")
    grid.addWidget(dialog.comfyui_workflow_path_edit, 9, 1)
    grid.addWidget(InfoButton(
        "Optionaler eigener API-Workflow. Beim HDRTVDM-Profil verwendet DragonTools ohne Pfad seinen eingebauten "
        "Voll-Datei-Streaming-Workflow. Ein gespeicherter ComfyUI-Testworkflow mit statischem Load Image (z. B. "
        "banner.png) ist kein gültiger DragonTools-Video-Workflow und wird automatisch verworfen; HDRTVDM fällt dann "
        "auf den eingebauten Voll-Datei-Workflow zurück. Das Video wird frameweise über Pipes verarbeitet; eine komplette "
        "TIFF-Sequenz wird nicht auf Platte geschrieben."
    ), 9, 2)
    return 10


__all__ = ["build_comfyui_fields"]
