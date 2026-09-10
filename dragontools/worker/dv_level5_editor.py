# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .converter_utils import _parse_crop, _physical_crop_level5_json


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
            self._log("DV: Kein physischer Crop -> RPU unverändert.", "info")
            return rpu_orig

        cw, ch, cx, cy = crop_params
        vid = media_info.primary_video
        sw = vid.width if vid else 0
        sh = vid.height if vid else 0

        self._log(
            f"DV: Physischer Crop aktiv - Quellauflösung={sw}x{sh}, "
            f"Zielauflösung={cw}x{ch}, crop-String={crop}",
            "info",
        )

        if not (sw and sh):
            self._log(
                "DV: Quellauflösung unbekannt - RPU-Crop nicht möglich. Abbruch.",
                "error",
            )
            return None

        # Wichtig: Die RPU darf NICHT noch einmal die Pixel ausblenden, die
        # FFmpeg bereits physisch aus dem HEVC-Frame entfernt hat. Bei z.B.
        # 3840x2160 -> crop=3240:2160:300:0 ist das Ziel-Frame bereits 3240px
        # breit. L5 left/right=300 würde am DV-TV einen zweiten Crop auslösen.
        #
        # dovi_tool dokumentiert für genau diesen Fall active_area.crop=true.
        # Diese Operation setzt die Active-Area-Offsets über die gesamte RPU
        # auf 0 und ist robuster als ein zusätzliches Null-Preset mit "all".
        _physical_crop_level5_json(edit_json)
        left = right = top = bottom = 0

        self._log(
            "DV: RPU wird an den bereits physisch gecroppten Zielstream angepasst: "
            f"L5 left={left} right={right} top={top} bottom={bottom}. "
            f"Physischer Quell-Crop: L={cx} R={max(0, sw-cw-cx)} "
            f"T={cy} B={max(0, sh-ch-cy)}.",
            "info",
        )

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
            verify_json = edit_json.with_name(f"{edit_json.stem}_verify.json")
            if self._verify_zero_level5(run_cmd, rpu_final=rpu_final, export_json=verify_json):
                self._log(
                    f"DV: RPU-Crop erfolgreich und verifiziert -> {rpu_final.name} "
                    f"({rpu_final.stat().st_size:,} Byte), L5=0/0/0/0",
                    "info",
                )
                return rpu_final
            self._log(
                "DV: RPU-Crop wurde erzeugt, aber die Level-5-Nachprüfung ist fehlgeschlagen. "
                "Die RPU wird nicht injiziert.",
                "error",
            )
        else:
            self._log(
                "DV: RPU-Crop fehlgeschlagen "
                "(rpu_final fehlt, ist leer oder dovi_tool meldete einen Fehler).",
                "error",
            )

        self._log(
            "DV: Originale RPU wird bei physischem Crop NICHT als Fallback verwendet, "
            "weil sonst ein doppelter Active-Area-Crop am Dolby-Vision-Gerät entstehen kann.",
            "error",
        )
        fail_dir = save_failure_artifacts(level5_proc)
        self._log(f"Artefakte gesichert: {fail_dir}", "error")
        self._log("Ausgabe ohne sicheren Dolby-Vision-RPU-Crop wurde verworfen.", "warn")
        return None

    def _verify_zero_level5(self, run_cmd, *, rpu_final: Path, export_json: Path) -> bool:
        """Verifiziert fail-closed, dass *alle* exportierten L5-Offsets 0 sind."""
        attempts = (
            [self._dovi_tool_path, "export", "-i", str(rpu_final), "-d", f"level5={export_json}"],
            [self._dovi_tool_path, "export", "-i", str(rpu_final), "--data", f"level5={export_json}"],
        )
        for cmd in attempts:
            export_json.unlink(missing_ok=True)
            result = run_cmd(cmd, allow_error=True)
            rc = getattr(result, "returncode", result)
            if rc == 0 and export_json.exists() and export_json.stat().st_size > 0:
                break
        else:
            self._log("DV: Finale RPU-Level-5-Daten konnten nicht exportiert werden.", "error")
            return False

        try:
            payload = json.loads(export_json.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, TypeError) as exc:
            self._log(f"DV: Level-5-Nachprüfung konnte JSON nicht lesen: {exc}", "error")
            return False

        offsets: list[tuple[int, int, int, int]] = []
        self._collect_offsets(payload, offsets)
        if not offsets:
            self._log("DV: Level-5-Nachprüfung fand keine Active-Area-Offsets.", "error")
            return False

        unique = list(dict.fromkeys(offsets))
        nonzero = [item for item in unique if any(int(value) != 0 for value in item)]
        if nonzero:
            sample = ", ".join(
                f"L={l}/R={r}/T={t}/B={b}" for l, r, t, b in nonzero[:4]
            )
            self._log(
                "DV: Level-5-Nachprüfung FEHLER - nach physischem Video-Crop sind "
                f"noch nicht-null Active-Area-Werte vorhanden: {sample}",
                "error",
            )
            return False

        self._log("DV: Level-5-Nachprüfung OK - alle Active-Area-Offsets sind 0.", "info")
        return True

    @classmethod
    def _collect_offsets(cls, node, result: list[tuple[int, int, int, int]]) -> None:
        if isinstance(node, dict):
            aliases = (
                ("left", "right", "top", "bottom"),
                (
                    "active_area_left_offset",
                    "active_area_right_offset",
                    "active_area_top_offset",
                    "active_area_bottom_offset",
                ),
            )
            for names in aliases:
                if all(name in node for name in names):
                    try:
                        result.append(tuple(int(node[name]) for name in names))
                    except (TypeError, ValueError):
                        pass
                    break
            for value in node.values():
                cls._collect_offsets(value, result)
        elif isinstance(node, list):
            for value in node:
                cls._collect_offsets(value, result)

    @staticmethod
    def _editor_ok(path: Path, proc=None) -> bool:
        return getattr(proc, "returncode", 0) == 0 and path.exists() and path.stat().st_size > 0
