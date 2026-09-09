# -*- coding: utf-8 -*-
from __future__ import annotations
from pathlib import Path
from PyQt6.QtWidgets import QCheckBox, QComboBox, QFrame, QGridLayout, QGroupBox, QLabel, QLineEdit, QMessageBox, QPushButton, QSpinBox
from ...core import settings as cfg
from ...core.parallel_settings import migrate_parallel_defaults
from ...core.paths import find_tool, get_tool_paths, invalidate_tool_paths
from ..info_button import InfoButton
from .base import SettingsSection


class RuntimeToolsSection(SettingsSection):
    section_keys = ("tools", "defaults", "parallel")

    def build(self, vl) -> None:
        d = self.dialog
        # ── Tool-Pfade ─────────────────────────────────────────────────
        tool_grp = QGroupBox("Tool-Pfade")
        d._section_widgets["tools"] = tool_grp
        tg = QGridLayout(tool_grp)
        tg.setVerticalSpacing(4)
        tg.setColumnStretch(2, 1)  # Edit-Feld dehnt sich aus

        # Zeile 0: Erklärung + Alle-Suchen Button nebeneinander
        desc_lbl = QLabel(
            "Nur ausfüllen wenn ein Tool <b>nicht automatisch gefunden</b> wird (F9).")
        desc_lbl.setWordWrap(True)
        tg.addWidget(desc_lbl, 0, 0, 1, 3)

        all_auto_btn = QPushButton("🔍 Alle Tools automatisch suchen")
        all_auto_btn.setStyleSheet(
            "background:#0078d7;color:white;font-weight:bold;padding:5px 12px;")
        all_auto_btn.clicked.connect(d.auto_detect_all)
        tg.addWidget(all_auto_btn, 0, 3, 1, 2)

        # Trennlinie
        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#ddd;")
        tg.addWidget(sep, 1, 0, 1, 5)

        d._tool_cbs:   dict[str, QCheckBox] = {}
        d._tool_edits: dict[str, QLineEdit] = {}

        tool_infos = {
            "ffmpeg":         ("FFmpeg + FFprobe",
                               "Ordner mit ffmpeg.exe und ffprobe.exe angeben.\n"
                               "Beide Tools liegen immer im gleichen Ordner."),
            "mkv":            ("MKVToolNix",
                                "Ordner mit mkvtoolnix-gui.exe, mkvmerge.exe, mkvextract.exe usw.\n"
                                "Wird für MKV-Remuxing und Untertitel-Werkzeuge genutzt."),
            "makemkvcon":     ("MakeMKV CLI",
                               "Ordner mit makemkvcon64.exe / makemkvcon.exe.\n"
                               "Wird für spätere MakeMKV-CLI-Workflows genutzt."),
            "rmts":           ("RMTS (RenameMyTVSeries)",
                               "Serien-Umbenennungstool. Wird extern geöffnet."),
            "handbrake":      ("HandBrake",
                               "HandBrake.exe / HandBrakeCLI.exe – Wird extern geöffnet."),
            "mediainfo":      ("MediaInfo",
                               "MediaInfo.exe – erweiterte HDR/DV-Erkennung."),
            "dovi_tool":      ("dovi_tool",
                               "dovi_tool.exe – Dolby Vision RPU extrahieren/injizieren."),
            "hdr10plus_tool": ("hdr10plus_tool",
                               "hdr10plus_tool.exe – HDR10+ Metadaten."),
            "mp4box":         ("MP4Box (GPAC)",
                               "MP4Box.exe – DV-MP4 Muxing."),
        }

        # Spalten-Header
        tg.addWidget(QLabel("<b>Tool</b>"), 2, 0)
        tg.addWidget(QLabel("<b>Ordner</b>"), 2, 2)
        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#ddd;")
        tg.addWidget(sep2, 3, 0, 1, 5)
        # Hinweistext unter dem Header, volle Breite, eigene Zeile
        hint_lbl = QLabel(
            "ℹ️  Der eingetragene Pfad gilt immer wenn ausgefüllt – "
            "unabhängig davon ob die Checkbox gesetzt ist."
        )
        hint_lbl.setWordWrap(True)
        hint_lbl.setStyleSheet("color:#475569; font-size:11px; padding:2px 0;")
        tg.addWidget(hint_lbl, 4, 0, 1, 5)
        row = 5

        for tool, (cb_key, dir_key) in cfg.TOOL_KEYS.items():
            label, info = tool_infos.get(tool, (tool, tool))

            # Checkbox + Info in Spalte 0-1
            cb = QCheckBox(label)
            d._tool_cbs[cb_key] = cb
            tg.addWidget(cb, row, 0)
            tg.addWidget(InfoButton(info), row, 1)

            # Edit-Feld in Spalte 2
            ed = QLineEdit()
            ed.setPlaceholderText("Ordner leer lassen = automatisch suchen")
            d._tool_edits[dir_key] = ed
            tg.addWidget(ed, row, 2)

            # Browse-Button Spalte 3
            browse_btn = QPushButton("…")
            browse_btn.setFixedWidth(28)
            browse_btn.clicked.connect(lambda _, e=ed: d.browse(e))
            tg.addWidget(browse_btn, row, 3)

            # Auto-Button Spalte 4
            auto_btn = QPushButton("🔍 Auto")
            auto_btn.setFixedWidth(70)
            auto_btn.setToolTip(f"{label} automatisch suchen")
            auto_btn.clicked.connect(lambda _, t=tool, e=ed: d.auto_detect(t, e))
            tg.addWidget(auto_btn, row, 4)

            row += 1
        vl.addWidget(tool_grp)

        # ── Standard-Video ─────────────────────────────────────────
        def_grp = QGroupBox("Standard-Werte")
        d._section_widgets["defaults"] = def_grp
        dg = QGridLayout(def_grp)
        dg.addWidget(QLabel("Standard-Codec:"), 0, 0)
        d.default_codec_combo = QComboBox()
        d.default_codec_combo.addItems(["h265", "h264", "av1"])
        d.default_codec_combo.setCurrentText(
            d.settings.value("defaults/codec", "h265", type=str)
        )
        dg.addWidget(d.default_codec_combo, 0, 1)
        dg.addWidget(InfoButton(
            "Bestimmt, welcher Converter-Tab beim App-Start aktiv ist.\n"
            "h265 → H.265-Tab  |  h264 → H.264-Tab  |  av1 → AV1-Tab\n"
            "Jeder Tab hat seinen Codec fest eingebaut – diese Einstellung "
            "steuert nur den Startfokus."
        ), 0, 2)
        dg.addWidget(QLabel("Standard-Zieltyp (Serien):"), 1, 0)
        d.series_default_combo = QComboBox()
        d.series_default_combo.addItems(["Anime", "TV"])
        d.series_default_combo.setCurrentText(
            d.settings.value(cfg.SET_KEY_SERIES_DEFAULT_TYPE, "Anime", type=str)
        )
        dg.addWidget(d.series_default_combo, 1, 1)
        dg.addWidget(InfoButton(
            "Welcher Typ (Anime oder TV) im Preflight-Dialog für Serien vorausgewählt wird. "
            "Fallback ist Anime."
        ), 1, 2)
        dg.addWidget(QLabel("Countdown Herunterfahren (s):"), 2, 0)
        d.shutdown_countdown_spin = QSpinBox()
        d.shutdown_countdown_spin.setRange(5, 300)
        d.shutdown_countdown_spin.setValue(
            int(d.settings.value(cfg.SET_KEY_SHUTDOWN_COUNTDOWN, 30, type=int))
        )
        d.shutdown_countdown_spin.setSuffix(" s")
        dg.addWidget(d.shutdown_countdown_spin, 2, 1)
        dg.addWidget(InfoButton(
            "Wie viele Sekunden der Countdown-Dialog wartet, bevor der PC automatisch "
            "heruntergefahren wird. Minimum 5 s, Maximum 300 s."
        ), 2, 2)
        vl.addWidget(def_grp)

        # ── Parallele Bearbeitung ───────────────────────────────────────
        parallel_grp = QGroupBox("Parallele Bearbeitung")
        d._section_widgets["parallel"] = parallel_grp
        pg_parallel = QGridLayout(parallel_grp)
        parallel_desc = QLabel(
            "Legt fest, wie viele Dateien gleichzeitig konvertiert werden dürfen. "
            "1 bedeutet: Verarbeitung wie bisher nacheinander."
        )
        parallel_desc.setWordWrap(True)
        pg_parallel.addWidget(parallel_desc, 0, 0, 1, 3)

        pg_parallel.addWidget(QLabel("CPU-Encoder:"), 1, 0)
        d.parallel_cpu_spin = QSpinBox()
        d.parallel_cpu_spin.setRange(1, cfg.MAX_PARALLEL_JOBS)
        d.parallel_cpu_spin.setSuffix(" Datei(en)")
        pg_parallel.addWidget(d.parallel_cpu_spin, 1, 1)
        pg_parallel.addWidget(InfoButton(
            "Gilt für Software-Encoding mit libx264/libx265/SVT-AV1. "
            "Standard ist 1 Datei, weil x265 eine 8-Kern-CPU meist bereits gut auslastet. "
            "2 Dateien parallel erst ab etwa 12-16 echten Kernen oder nach eigenem Test."
        ), 1, 2)

        pg_parallel.addWidget(QLabel("GPU-Encoder:"), 2, 0)
        d.parallel_gpu_spin = QSpinBox()
        d.parallel_gpu_spin.setRange(1, cfg.MAX_PARALLEL_JOBS)
        d.parallel_gpu_spin.setSuffix(" Datei(en)")
        pg_parallel.addWidget(d.parallel_gpu_spin, 2, 1)
        pg_parallel.addWidget(InfoButton(
            "Gilt für NVENC, QSV und AMF. Standard ist 2 Dateien parallel. "
            "Leistungsstarke NVIDIA-GPUs können je nach Modell, Filterlast und Datenträger auch 3-4 schaffen."
        ), 2, 2)
        vl.addWidget(parallel_grp)


    def load(self) -> None:
        d, s = self.dialog, self.settings
        migrate_parallel_defaults(s)
        d.default_codec_combo.setCurrentText(s.value("defaults/codec", "h265", type=str))
        d.series_default_combo.setCurrentText(s.value(cfg.SET_KEY_SERIES_DEFAULT_TYPE, "Anime", type=str))
        d.shutdown_countdown_spin.setValue(int(s.value(cfg.SET_KEY_SHUTDOWN_COUNTDOWN, 30, type=int)))
        d.parallel_cpu_spin.setValue(int(s.value(cfg.SET_KEY_PARALLEL_CPU_JOBS, cfg.DEFAULT_PARALLEL_CPU_JOBS, type=int)))
        d.parallel_gpu_spin.setValue(int(s.value(cfg.SET_KEY_PARALLEL_GPU_JOBS, cfg.DEFAULT_PARALLEL_GPU_JOBS, type=int)))
        for key, cb in d._tool_cbs.items():
            cb.setChecked(s.value(key, False, type=bool))
        for key, ed in d._tool_edits.items():
            ed.setText(s.value(key, "", type=str))

    def save(self) -> bool:
        d, s = self.dialog, self.settings
        s.setValue("defaults/codec", d.default_codec_combo.currentText())
        s.setValue(cfg.SET_KEY_SERIES_DEFAULT_TYPE, d.series_default_combo.currentText())
        s.setValue(cfg.SET_KEY_SHUTDOWN_COUNTDOWN, d.shutdown_countdown_spin.value())
        s.setValue(cfg.SET_KEY_PARALLEL_CPU_JOBS, d.parallel_cpu_spin.value())
        s.setValue(cfg.SET_KEY_PARALLEL_GPU_JOBS, d.parallel_gpu_spin.value())
        for key, cb in d._tool_cbs.items():
            s.setValue(key, cb.isChecked())
        for key, ed in d._tool_edits.items():
            s.setValue(key, ed.text().strip())
        invalidate_tool_paths()
        return True

    def auto_detect(self, tool: str, edit) -> None:
        d = self.dialog
        names = {
            "ffmpeg": ("ffmpeg.exe", "ffmpeg"),
            "mkv": ("mkvtoolnix-gui.exe", "mkvtoolnix-gui", "mkvmerge.exe", "mkvmerge"),
            "makemkvcon": ("makemkvcon64.exe", "makemkvcon.exe", "makemkvcon"),
            "rmts": ("RenameMyTVSeries.exe", "rmts.exe", "RenameMyTVSeries"),
            "handbrake": ("HandBrakeCLI.exe", "HandBrakeCLI"),
            "mediainfo": ("MediaInfo.exe", "mediainfo"),
            "dovi_tool": ("dovi_tool.exe", "dovi_tool"),
            "hdr10plus_tool": ("hdr10plus_tool.exe", "hdr10plus_tool"),
            "mp4box": ("MP4Box.exe", "mp4box"),
        }.get(tool, (tool,))
        found = find_tool(names[0], *names[1:])
        if found != names[0]:
            found_path = Path(found).resolve()
            edit.setText(str(found_path.parent))
            QMessageBox.information(d, "Gefunden", f"{tool} gefunden:\n{found_path}")
        else:
            QMessageBox.warning(
                d,
                "Nicht gefunden",
                f"{tool} wurde nicht automatisch gefunden.\nBitte Pfad manuell eingeben.",
            )

    def auto_detect_all(self) -> None:
        d = self.dialog
        tp = get_tool_paths()
        tool_map = {
            "ffmpeg": (tp.ffmpeg, "ffmpeg.exe"),
            "mkv": (tp.mkvmerge, "mkvmerge.exe"),
            "makemkvcon": (tp.makemkvcon, "makemkvcon64.exe / makemkvcon.exe"),
            "rmts": (tp.rmts, "RenameMyTVSeries.exe"),
            "handbrake": (tp.handbrake_cli, "HandBrake.exe / HandBrakeCLI.exe"),
            "mediainfo": (tp.mediainfo, "MediaInfo.exe"),
            "dovi_tool": (tp.dovi_tool, "dovi_tool.exe"),
            "hdr10plus_tool": (tp.hdr10plus_tool, "hdr10plus_tool.exe"),
            "mp4box": (tp.mp4box, "MP4Box.exe"),
        }
        missing: list[str] = []
        lines: list[str] = []
        for tool_key, (result, display_name) in tool_map.items():
            if tool_key not in cfg.TOOL_KEYS:
                continue
            cb_key, dir_key = cfg.TOOL_KEYS[tool_key]
            found = bool(result and Path(result).exists())
            if found:
                tool_dir = str(Path(result).resolve().parent)
                if dir_key in d._tool_edits:
                    d._tool_edits[dir_key].setText(tool_dir)
                if cb_key in d._tool_cbs:
                    d._tool_cbs[cb_key].setChecked(True)
                lines.append(f"  ✅ {display_name}  ({tool_dir})")
            else:
                missing.append(display_name)
                lines.append(f"  ❌ {display_name}  (nicht gefunden)")
        msg = "Ergebnis:\n\n" + "\n".join(lines)
        if missing:
            msg += "\n\nNicht gefundene Tools bitte manuell eintragen."
        QMessageBox.information(d, "Autosuche abgeschlossen", msg)
