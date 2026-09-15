# -*- coding: utf-8 -*-
"""Lossless Dolby-Vision profile preparation for the remux workflow."""
from __future__ import annotations

import json
from pathlib import Path

from ..core.timeout_settings import get_timeout


class DVRemuxProfileService:
    def __init__(self, worker, process_runner) -> None:
        self.worker = worker
        self.process_runner = process_runner


    def detect_p7_enhancement_layer(self, source_hevc: str | Path, scratch_dir: str | Path) -> str | None:
        """Best-effort FEL/MEL probe from the first RPU frame.

        MediaInfo does not reliably expose the P7 enhancement-layer variant.
        dovi_tool does, so extract only one RPU frame and inspect its JSON.
        Failure is informational only; profile conversion itself remains fail-closed.
        """
        source = Path(source_hevc)
        scratch = Path(scratch_dir)
        rpu = scratch / "p7_probe_rpu.bin"
        rpu.unlink(missing_ok=True)
        timeout = get_timeout("dv_rpu_extract")
        extract_cmd = [
            self.worker.tools.dovi_tool,
            "extract-rpu",
            "-l", "1",
            "-i", str(source),
            "-o", str(rpu),
        ]
        rc, _stdout, _stderr = self.process_runner.run_abortable_capture(
            extract_cmd, timeout_s=timeout
        )
        if rc != 0 or not rpu.exists() or rpu.stat().st_size <= 0 or self._abort_current_file():
            self.worker.log(
                "  ⚠️ DV7: FEL/MEL-Typ konnte vor der P8.1-Normalisierung nicht bestimmt werden.",
                "warn",
            )
            return None

        info_cmd = [
            self.worker.tools.dovi_tool,
            "info",
            "-i", str(rpu),
            "-f", "0",
        ]
        rc, stdout, stderr = self.process_runner.run_abortable_capture(
            info_cmd, timeout_s=timeout
        )
        if rc != 0 or self._abort_current_file():
            self.worker.log(
                "  ⚠️ DV7: dovi_tool konnte den Enhancement-Layer-Typ nicht auswerten.",
                "warn",
            )
            return None
        payload = _json_object(stdout or stderr or "")
        subprofile = str(payload.get("subprofile") or "").strip().upper() if payload else ""
        if subprofile == "FEL":
            self.worker.log(
                "  ⚠️ DV7 FEL erkannt: P7→P8.1 verwirft den Full Enhancement Layer; "
                "dessen zusätzliche Bildinformation kann im P8.1-Ziel nicht erhalten werden.",
                "warn",
            )
            return "FEL"
        if subprofile == "MEL":
            self.worker.log(
                "  ℹ️ DV7 MEL erkannt: Der Enhancement Layer enthält keine zusätzliche FEL-Bildinformation; "
                "P7→P8.1 verwirft ihn beim Kompatibilitäts-Remux.",
                "info",
            )
            return "MEL"
        self.worker.log(
            "  ⚠️ DV7: dovi_tool lieferte keinen eindeutigen FEL/MEL-Typ.",
            "warn",
        )
        return None

    def normalize_to_p81(self, source_hevc: str | Path, output_hevc: str | Path) -> bool:
        source = Path(source_hevc)
        output = Path(output_hevc)
        output.unlink(missing_ok=True)
        self.worker.log(
            "  🌈 Normalisiere Dolby Vision mit dovi_tool Mode 2 auf Profile 8.1 ...",
            "info",
        )
        cmd = [
            self.worker.tools.dovi_tool,
            "-m", "2",
            "convert",
            "--discard",
            str(source),
            "-o", str(output),
        ]
        timeout = get_timeout("dv_dovi_convert")
        rc, stdout, stderr = self.process_runner.run_abortable_capture(cmd, timeout_s=timeout)
        if self._abort_current_file():
            self.worker.log("dovi_tool-Profilnormalisierung abgebrochen.", "warn")
            return False
        if rc != 0:
            detail = "\n".join(
                line for line in ((stderr or "") + "\n" + (stdout or "")).splitlines()
                if line.strip()
            )[-1200:]
            self.worker.log(f"❌ dovi_tool Profile-8.1-Normalisierung fehlgeschlagen (rc={rc}).", "error")
            if detail:
                self.worker.log(f"  dovi_tool: {detail}", "error")
            return False
        if not output.exists() or output.stat().st_size <= 0:
            self.worker.log("❌ dovi_tool meldete Erfolg, erzeugte aber keinen gültigen P8.1-Bitstream.", "error")
            return False
        return True

    def _abort_current_file(self) -> bool:
        return bool(
            getattr(self.worker, "abort_requested", False)
            and getattr(self.worker, "abort_type", None) == "sofort"
        )


def _json_object(text: str) -> dict:
    raw = str(text or "")
    start = raw.find("{")
    end = raw.rfind("}")
    if start < 0 or end < start:
        return {}
    try:
        value = json.loads(raw[start:end + 1])
    except (json.JSONDecodeError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}
