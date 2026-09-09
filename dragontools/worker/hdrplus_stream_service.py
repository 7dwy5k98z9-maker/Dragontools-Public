# -*- coding: utf-8 -*-
from __future__ import annotations

import traceback
from pathlib import Path
from typing import Callable

from .converter_utils import _fs


class HDRPlusStreamService:
    """Container-/Bitstream-nahe I/O-Helfer des HDR10+-Pfads."""

    def __init__(self, *, ffmpeg_path: str, log: Callable[[str, str], None]) -> None:
        self._ffmpeg = ffmpeg_path
        self._log = log

    def extract_hevc_annexb(
        self,
        input_path: str,
        output_hevc: str,
        *,
        run_tool: Callable[..., bool],
    ) -> bool:
        try:
            src = Path(input_path)
            out = Path(output_hevc)
            self._log(f"HDR10+: Extrahiere HEVC-AnnexB aus {src.name} …", "info")
            cmd = [
                self._ffmpeg, "-y", "-loglevel", "error",
                "-i", input_path,
                "-map", "0:v:0",
                "-c:v", "copy",
                "-bsf:v", "hevc_mp4toannexb",
                "-an", "-sn", "-dn",
                "-f", "hevc",
                output_hevc,
            ]
            if not run_tool(cmd, label="HDR10+: HEVC-Extraktion", tool_name="ffmpeg"):
                return False
            if not out.exists():
                self._log(f"❌ HDR10+: HEVC-Datei wurde nicht erzeugt: {out.name}", "error")
                return False
            size = out.stat().st_size
            if size < 1024:
                self._log(f"❌ HDR10+: HEVC-Datei ist unplausibel klein ({size} Bytes): {out.name}", "error")
                return False
            self._log(f"HDR10+: HEVC-Extraktion erfolgreich -> {out.name} ({_fs(size)})", "info")
            return True
        except Exception:
            self._log(f"❌ Unbehandelte Ausnahme in _extract_hevc_annexb() bei {Path(input_path).name}", "error")
            self._log(traceback.format_exc(), "error")
            return False

    def verify_final_hdr10plus(
        self,
        output_path: str,
        expected_json: Path,
        *,
        run_tool: Callable[..., bool],
        run_tool_rc: Callable[..., int],
        bitstream_service,
    ) -> bool:
        output = Path(output_path)
        root = expected_json.parent
        final_stream = root / "final_verify.hevc"
        verify_json = root / "final_verify_hdr10plus.json"
        final_stream.unlink(missing_ok=True)
        verify_json.unlink(missing_ok=True)

        cmd = [
            self._ffmpeg, "-y", "-loglevel", "error",
            "-i", str(output),
            "-map", "0:v:0", "-c:v", "copy",
        ]
        if output.suffix.lower() == ".mp4":
            cmd += ["-bsf:v", "hevc_mp4toannexb"]
        cmd += ["-an", "-sn", "-dn", "-f", "hevc", str(final_stream)]
        if not run_tool(
            cmd,
            label="HDR10+: finalen HEVC-Videostream extrahieren",
            tool_name="ffmpeg",
        ):
            return False
        if not final_stream.exists() or final_stream.stat().st_size < 1024:
            self._log("❌ HDR10+: finaler HEVC-Prüf-Bitstream fehlt oder ist unplausibel klein.", "error")
            return False

        ok = bitstream_service.verify_metadata(
            run_tool_rc,
            source_stream=final_stream,
            scratch_json=verify_json,
            expected_json=expected_json,
        )
        if not ok:
            self._log(
                f"❌ HDR10+: Nachprüfung nach finalem {output.suffix.upper().lstrip('.')}-Mux fehlgeschlagen.",
                "error",
            )
            return False
        self._log(
            f"✅ HDR10+: finale {output.suffix.upper().lstrip('.')} enthält semantisch identische dynamische Metadaten.",
            "info",
        )
        return True
