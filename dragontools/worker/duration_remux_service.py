# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from .duration_repair_runtime import DurationRepairRuntime
from .tool_runner import log_tool_failure
from .workflow_engine import WorkflowVerifyResult
from .verification_control import stopped
from .duration_packet_integrity import PacketIntegrityVerifier


class DurationRemuxService:
    """Stage 1: lossless container remux used for duration repair."""

    def __init__(self, runtime: DurationRepairRuntime) -> None:
        self._runtime = runtime
        self._packet_integrity = PacketIntegrityVerifier(
            ffprobe_path=getattr(runtime, 'ffprobe_path', ''), run_tool=runtime.run_tool)

    def normal_remux_tool(self, container: str) -> tuple[str, str]:
        container_name = str(container or "").strip().lower().lstrip(".")
        if container_name == "mp4":
            return self._runtime.mp4box_path, "MP4Box"
        if container_name == "mkv":
            return self._runtime.mkvmerge_path, "MKVToolNix"
        return "", "Container-Werkzeug"

    def attempt(
        self,
        *,
        out: Path,
        container: str,
        expected_duration_ms: int | None,
        source_has_audio: bool,
        initial_result: WorkflowVerifyResult,
        expected_contract=None,
        verified_hdr10plus: bool = False,
        verified_dolby_vision: bool = False,
    ) -> tuple[WorkflowVerifyResult, float | None, bool, str]:
        container_name = str(container or "").strip().lower().lstrip(".")
        tool_path, tool_label = self.normal_remux_tool(container_name)
        if not tool_path:
            return initial_result, None, False, f"Kein Remux-Werkzeug für {container_name or 'Container'} konfiguriert."

        self._runtime.log(f"ℹ️ [Reparatur 1/2] Normaler {tool_label}-Remux startet.", "info")
        tmp = out.with_name(f"{out.stem}.duration_remux_{uuid4().hex}{out.suffix}")
        if container_name == "mp4":
            command = [self._runtime.mp4box_path, "-new", str(tmp), "-add", str(out)]
            failure_tool = "MP4Box"
        else:
            command = [self._runtime.mkvmerge_path, "-o", str(tmp), str(out)]
            failure_tool = "mkvmerge"

        try:
            run = self._runtime.run_tool(command, label=f"{tool_label}-Remux")
            max_ok_rc = 1 if container_name == "mkv" else 0
            if (run.returncode not in range(max_ok_rc + 1)
                    or stopped(run, getattr(self._runtime, 'worker', None))
                    or not tmp.exists() or tmp.stat().st_size < 1024):
                stderr = (run.stderr or run.stdout or f"{failure_tool} fehlgeschlagen.").strip()
                self._runtime.log(f"❌ Automatischer {tool_label}-Remux fehlgeschlagen.", "error")
                log_tool_failure(
                    run,
                    label=f"Automatischer {tool_label}-Remux",
                    log=self._runtime.log,
                    tool_name=failure_tool,
                )
                if stderr:
                    self._runtime.log(f"   {failure_tool}: {stderr.splitlines()[-1]}", "error")
                self._runtime.safe_unlink(tmp)
                return initial_result, None, False, "Automatischer Remux fehlgeschlagen."
            if container_name == "mkv" and run.returncode == 1:
                self._runtime.log("⚠️ mkvmerge meldete Warnungen, Remux-Datei wird trotzdem geprüft.", "warn")
        except Exception as exc:
            self._runtime.safe_unlink(tmp)
            self._runtime.log(f"❌ Automatischer {tool_label}-Remux fehlgeschlagen: {exc}", "error")
            return initial_result, None, False, "Automatischer Remux fehlgeschlagen."

        verify_kwargs = {
            "expected_duration_ms": expected_duration_ms,
            "source_has_audio": source_has_audio,
        }
        if expected_contract is not None:
            verify_kwargs["expected_contract"] = expected_contract
        if verified_hdr10plus:
            verify_kwargs["verified_hdr10plus"] = True
        if verified_dolby_vision:
            verify_kwargs["verified_dolby_vision"] = True
        # Der Remux ist nur ein Kandidat.  Er darf die vorhandene Encode-
        # Ausgabe erst ersetzen, nachdem der komplette Output-Vertrag auf der
        # Staging-Datei bestanden wurde.  So bleibt bei Stream-/Metadaten- oder
        # Laufzeitfehlern der vorherige Kandidat fuer weitere Reparatur bzw.
        # Diagnose erhalten.
        remux_result = self._runtime.output_verifier.verify(str(tmp), container, **verify_kwargs)
        remux_s = remux_result.duration_s
        if remux_result.ok and not self._verify_lossless(out, tmp, expected_duration_ms, remux_result):
            remux_result.duration_ok = False
        if remux_result.ok and not stopped(run, getattr(self._runtime, 'worker', None)):
            try:
                self._runtime.replace_file(tmp, out)
            except Exception as exc:
                self._runtime.log(
                    f"❌ Verifizierter {tool_label}-Remux konnte nicht committed werden: {exc}. "
                    f"Der geprüfte Kandidat bleibt zur Recovery erhalten: {tmp}",
                    "error",
                )
                return initial_result, remux_s, False, "Verifizierter Remux konnte nicht committed werden."
            expected_s = expected_duration_ms / 1000.0 if expected_duration_ms else None
            self._runtime.log(f"✅ Laufzeit durch automatischen {tool_label}-Remux korrigiert.", "info")
            self._runtime.log(
                f"   Quelle: {_fmt_duration(expected_s)} | nach Remux: {_fmt_duration(remux_s)}",
                "info",
            )
            return remux_result, remux_s, True, ""

        self._runtime.log("⚠️ Normaler Remux konnte die Laufzeit nicht korrigieren.", "warn")
        self._runtime.safe_unlink(tmp)
        return remux_result, remux_s, False, "Normaler Remux erfolglos."

    def _verify_lossless(self, out, tmp, expected_duration_ms, result):
        packets = self._packet_integrity.validate(str(out), str(tmp),
            reference_duration_s=expected_duration_ms / 1000 if expected_duration_ms else None,
            frame_rate=None, tolerance_s=1.0)
        if packets.ok and packets.available:
            return True
        result.messages = list(result.messages or []) + list(packets.messages)
        return False


def _fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unbekannt"
    try:
        return f"{float(seconds):.1f}s"
    except (TypeError, ValueError):
        return "unbekannt"
