# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable


class HDR10PlusBitstreamService:
    """Kleine Hülle um hdr10plus_tool für HEVC-Bitstream-Metadaten."""

    # ToolInfo hängt von der hdr10plus_tool-Version ab; SceneInfoSummary wird
    # aus SceneInfo abgeleitet und kann zwischen Tool-Versionen neu aufgebaut
    # werden. Beides ist kein dynamischer HDR10+-Bildinhalt.
    _VOLATILE_JSON_KEYS = {"ToolInfo", "SceneInfoSummary"}

    def __init__(self, *, hdr10plus_tool_path: str, log: Callable[[str, str], None]) -> None:
        self._hdr10plus_tool_path = hdr10plus_tool_path
        self._log = log

    def _read_json(self, path: Path):
        if not path.exists():
            self._log(f"❌ HDR10+: Metadata-Datei wurde nicht erzeugt: {path.name}", "error")
            return None
        if path.stat().st_size < 16:
            self._log(f"❌ HDR10+: Metadata-Datei ist unplausibel klein: {path.name}", "error")
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            self._log(f"❌ HDR10+: Metadata-Datei ist kein gültiges JSON: {path.name}", "error")
            self._log(f"  JSON-Fehler: {exc}", "error")
            return None
        if payload in (None, {}, [], ""):
            self._log(f"❌ HDR10+: Metadata-Datei ist semantisch leer: {path.name}", "error")
            return None
        return payload

    def _valid_json(self, path: Path) -> bool:
        return self._read_json(path) is not None

    @staticmethod
    def _valid_stream(path: Path) -> bool:
        return path.exists() and path.stat().st_size >= 1024

    @classmethod
    def _semantic_payload(cls, payload):
        """Entfernt nur werkzeugabhängige, nicht inhaltliche JSON-Felder."""
        if not isinstance(payload, dict):
            return payload
        return {
            key: value
            for key, value in payload.items()
            if key not in cls._VOLATILE_JSON_KEYS
        }

    def extract_metadata(self, run_cmd, *, source_stream: Path, output_json: Path) -> bool:
        # Ein fehlgeschlagener Wiederholungsversuch darf niemals ein JSON eines
        # vorherigen Laufs als vermeintlich frisches Ergebnis weiterverwenden.
        output_json.unlink(missing_ok=True)
        self._log(f"HDR10+: Extrahiere Metadaten aus {source_stream.name} …", "info")
        rc = run_cmd(
            [
                self._hdr10plus_tool_path,
                "extract",
                str(source_stream),
                "-o",
                str(output_json),
            ],
            allow_error=True,
        )
        if rc != 0:
            self._log(f"❌ HDR10+: Metadata-Extract fehlgeschlagen (rc={rc})", "error")
            return False
        if not self._valid_json(output_json):
            return False
        self._log(f"HDR10+: Metadaten erfolgreich extrahiert -> {output_json.name}", "info")
        return True

    def inject_metadata(
        self,
        run_cmd,
        *,
        input_hevc: Path,
        metadata_json: Path,
        output_hevc: Path,
    ) -> bool:
        if not self._valid_json(metadata_json):
            self._log("❌ HDR10+: Injection abgebrochen – Quellmetadaten sind ungültig.", "error")
            return False
        output_hevc.unlink(missing_ok=True)
        self._log(f"HDR10+: Injiziere Metadaten in {input_hevc.name} …", "info")
        rc = run_cmd(
            [
                self._hdr10plus_tool_path,
                "inject",
                "-i",
                str(input_hevc),
                "-j",
                str(metadata_json),
                "-o",
                str(output_hevc),
            ],
            allow_error=True,
        )
        if rc != 0:
            self._log(f"❌ HDR10+: Metadata-Injection fehlgeschlagen (rc={rc})", "error")
            return False
        if not self._valid_stream(output_hevc):
            self._log(f"❌ HDR10+: Injizierter HEVC-Stream fehlt oder ist unplausibel: {output_hevc.name}", "error")
            return False
        self._log(f"HDR10+: Metadaten erfolgreich injiziert -> {output_hevc.name}", "info")
        return True

    def verify_metadata(
        self,
        run_cmd,
        *,
        source_stream: Path,
        scratch_json: Path,
        expected_json: Path | None = None,
    ) -> bool:
        scratch_json.unlink(missing_ok=True)
        if not self.extract_metadata(run_cmd, source_stream=source_stream, output_json=scratch_json):
            return False
        try:
            if expected_json is None:
                return True
            expected = self._read_json(expected_json)
            actual = self._read_json(scratch_json)
            if expected is None or actual is None:
                return False
            if self._semantic_payload(expected) != self._semantic_payload(actual):
                self._log(
                    "❌ HDR10+: Nachprüfung fehlgeschlagen – die finalen dynamischen "
                    "Metadaten weichen von der Quelle ab.",
                    "error",
                )
                return False
            self._log("HDR10+: Nachprüfung bestätigt identische dynamische Metadaten.", "info")
            return True
        finally:
            scratch_json.unlink(missing_ok=True)
