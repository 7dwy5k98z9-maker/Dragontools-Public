# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable

from .converter_utils import _level5_json, _parse_crop


class DVLevel5Editor:
    def __init__(self, *, dovi_tool_path: str, log: Callable[[str, str], None]) -> None:
        self._dovi_tool_path = dovi_tool_path
        self._log = log

    def resolve_rpu_for_crop(
        self,
        run_cmd,
        *,
        crop: str | None,
        media_info,
        rpu_orig: Path,
        rpu_final: Path,
        edit_json: Path,
        save_failure_artifacts,
    ) -> Path | None:
        crop_params = _parse_crop(crop)

        if not crop_params:
            self._log("DV: Kein Crop -> RPU unverändert.", "info")
            return rpu_orig

        cw, ch, _, _ = crop_params
        vid = media_info.primary_video
        sw = vid.width if vid else 0
        sh = vid.height if vid else 0

        self._log(
            f"DV: Crop aktiv - Quellauflösung={sw}x{sh}, "
            f"Zielauflösung={cw}x{ch}, crop-String={crop}",
            "info",
        )

        if not (sw and sh):
            self._log(
                "DV: Quellauflösung unbekannt - RPU-Crop nicht möglich. Abbruch.",
                "error",
            )
            return None

        # Der HEVC-Encode wird physisch gecroppt. Level-5-Active-Area-Werte
        # beziehen sich auf das *aktuelle* codierte Frame. Nach einem
        # 3840x2160 -> 3840x1596 Crop existieren die entfernten 282px-Balken
        # im Zielstream nicht mehr; top/bottom muessen deshalb 0 sein.
        l5 = _level5_json(cw, ch, cw, ch, 0, 0, edit_json)
        left = l5["active_area_left_offset"]
        right = l5["active_area_right_offset"]
        top = l5["active_area_top_offset"]
        bottom = l5["active_area_bottom_offset"]

        self._log(
            f"DV: Physischer Crop aktiv - Level 5 wird auf das Ziel-Frame "
            f"{cw}x{ch} normalisiert: left={left} right={right} "
            f"top={top} bottom={bottom} (Quelle {sw}x{sh}).",
            "info",
        )

        check_h = ch + top + bottom
        check_w = cw + left + right
        level5_proc = None

        if check_h != ch or check_w != cw:
            self._log(
                f"DV: Level 5 Konsistenzfehler "
                f"(berechnetes Ziel-Frame {check_w}x{check_h} != Encode {cw}x{ch}).",
                "error",
            )
        else:
            self._log("DV: Level 5 Konsistenzprüfung OK -> dovi_tool editor startet ...", "info")
            level5_proc = run_cmd(
                [
                    self._dovi_tool_path,
                    "editor",
                    "-i", str(rpu_orig),
                    "-j", str(edit_json),
                    "-o", str(rpu_final),
                ],
                allow_error=True,
                return_process=True,
            )

            if self._editor_ok(rpu_final, level5_proc):
                self._log(
                    f"DV: Level 5 erfolgreich -> "
                    f"RPU-Datei: {rpu_final.name} "
                    f"({rpu_final.stat().st_size:,} Byte)",
                    "info",
                )
                return rpu_final

            self._log(
                "DV: Level 5 fehlgeschlagen "
                "(rpu_final fehlt, ist leer oder dovi_tool meldete einen Fehler).",
                "error",
            )

        self._log(
            "DV: Level 2 AutoCrop-Fallback wird bei gecropptem Re-Encode nicht verwendet. "
            "Er kann eine RPU erzeugen, deren Active-Area nicht zum HEVC-Crop passt.",
            "error",
        )
        self._log(
            "DV: Level 5 fehlgeschlagen. Crop-Werte können nicht sicher in den RPU gesetzt werden. "
            "Originale RPU wird NICHT verwendet - Abbruch.",
            "error",
        )
        fail_dir = save_failure_artifacts(level5_proc)
        self._log(f"Artefakte gesichert: {fail_dir}", "error")
        self._log("MP4 ohne DV wurde zur manuellen Nachbearbeitung gespeichert.", "warn")
        return None

    @staticmethod
    def _editor_ok(path: Path, proc=None) -> bool:
        return getattr(proc, "returncode", 0) == 0 and path.exists() and path.stat().st_size > 0

