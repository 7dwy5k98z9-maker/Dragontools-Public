from __future__ import annotations

import json
import os
import time
import traceback
from pathlib import Path
from typing import Any

from PyQt6.QtCore import pyqtSignal

from .base_worker import BaseWorker
from ..core.logger import create_worker_logger
from ..core.media_analyzer import analyze_media
from ..core.paths import get_tool_paths
from ..core.timeout_settings import get_timeout
from .tool_runner import run_tool






class _UserAbortError(RuntimeError):
    pass


def _container_from_path(path: str) -> str:
    suffix = Path(path).suffix.lower()
    if suffix == ".mkv":
        return "mkv"
    if suffix in {".mp4", ".m4v"}:
        return "mp4"
    return suffix.lstrip(".") or "unknown"


def _container_from_format_name(format_name: str) -> str:
    text = (format_name or "").lower()
    if "matroska" in text or "webm" in text:
        return "mkv"
    if "mov,mp4" in text or "mp4" in text or "ipod" in text:
        return "mp4"
    return "unknown"


def _parse_fps(value: str | None) -> float | None:
    text = (value or "").strip()
    if not text or text in {"0/0", "0", "N/A"}:
        return None
    try:
        if "/" in text:
            num, den = text.split("/", 1)
            den_f = float(den)
            if den_f == 0:
                return None
            return round(float(num) / den_f, 6)
        return round(float(text), 6)
    except Exception:
        return None


def _audio_signature(streams: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "codec": (s.codec or "").lower(),
            "channels": int(s.channels or 0),
            "language": (s.language or "und").lower(),
        }
        for s in streams
    ]


def _subtitle_signature(streams: list[Any]) -> list[dict[str, Any]]:
    return [
        {
            "codec": (s.codec or "").lower(),
            "language": (s.language or "und").lower(),
            "forced": bool(s.forced),
        }
        for s in streams
    ]


class MergeThread(BaseWorker):
    """Produktive Basis für konservatives lossless Merge."""

    SUPPORTED_MODES = {"lossless", "check_only"}

    log_line = pyqtSignal(str)
    progress = pyqtSignal(int)
    file_progress = pyqtSignal(str, int, object)
    file_result = pyqtSignal(str, bool, str)
    finished = pyqtSignal()

    def __init__(
        self,
        files: list[str] | None = None,
        output_path: str | None = None,
        tools=None,
        mode: str = "lossless",
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.files = [str(Path(f).resolve()) for f in (files or [])]
        self.output_path = str(Path(output_path).resolve()) if output_path else None
        self.tools = tools or get_tool_paths()
        self.mode = mode

        self._logger = create_worker_logger(gui_callback=self.log_line.emit)
        self.log_file_path = str(self._logger.log_file) if self._logger.log_file else None

    def _run_json_ffprobe(self, path: str) -> dict[str, Any]:
        result = run_tool(
            [
                self.tools.ffprobe,
                "-v", "error",
                "-show_format",
                "-show_streams",
                "-of", "json",
                path,
            ],
            label="Merge ffprobe",
            timeout_s=get_timeout("media_analysis"),
            worker=self,
            log=self._log,
        )
        if result.aborted or self.abort_requested:
            raise _UserAbortError("Abgebrochen")
        if result.timed_out:
            raise RuntimeError("ffprobe: Timeout")
        if not result.ok:
            raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "ffprobe fehlgeschlagen")
        try:
            return json.loads(result.stdout or "{}")
        except Exception as exc:
            raise RuntimeError(f"ffprobe JSON ungültig: {exc}") from exc

    def run(self) -> None:
        self.progress.emit(0)
        self._logger.header([], "merge", len(self.files), "merge", None, self.mode)

        try:
            if self.mode not in self.SUPPORTED_MODES:
                msg = f"Merge-Modus '{self.mode}' wird nicht unterstützt."
                self._log(msg, "error")
                self.file_result.emit(self.output_path or "", False, msg)
                self.progress.emit(100)
                return

            if len(self.files) < 2:
                msg = "Für Merge werden mindestens zwei Eingabedateien benötigt."
                self._log(msg, "error")
                self.file_result.emit(self.output_path or "", False, msg)
                self.progress.emit(100)
                return

            if not self.output_path:
                msg = "Keine Zieldatei gesetzt."
                self._log(msg, "error")
                self.file_result.emit("", False, msg)
                self.progress.emit(100)
                return

            infos = self._analyze_inputs(self.files)
            if self.abort_requested:
                self.file_result.emit(self.output_path, False, "Abgebrochen")
                return

            plan = self._build_merge_plan(infos, self.output_path, self.mode)
            self.file_progress.emit(self.output_path, 35, plan)
            self.progress.emit(35)

            if self.mode == "check_only":
                reason_text = "; ".join(plan["reasons"]) or "Lossless Merge möglich."
                self.progress.emit(100)
                self.file_result.emit(
                    self.output_path,
                    bool(plan["lossless_possible"]),
                    reason_text,
                )
                return

            if not plan["lossless_possible"]:
                reason_text = "; ".join(plan["reasons"]) or "Lossless Merge nicht möglich."
                self._log(f"Lossless Merge abgelehnt: {reason_text}", "warn")
                self.progress.emit(100)
                self.file_result.emit(self.output_path, False, reason_text)
                return

            ok = self._run_lossless_merge(plan)
            if self.abort_requested:
                self.file_result.emit(self.output_path, False, "Abgebrochen")
                return

            self.progress.emit(100)
            if ok:
                self.file_result.emit(self.output_path, True, self.output_path)
            else:
                self.file_result.emit(self.output_path, False, "Lossless Merge fehlgeschlagen")
        except _UserAbortError:
            self.file_result.emit(self.output_path or "", False, "Abgebrochen")
        except Exception as exc:
            self._log("Unbehandelte Ausnahme im MergeThread.", "error")
            self._log(traceback.format_exc(), "error")
            self.file_result.emit(self.output_path or "", False, str(exc))
        finally:
            self.current_process = None
            self.finished.emit()

    def _analyze_inputs(self, files: list[str]) -> list[dict[str, Any]]:
        infos: list[dict[str, Any]] = []
        total = max(1, len(files))

        for index, path in enumerate(files, start=1):
            if self.abort_requested:
                raise _UserAbortError("Abgebrochen")

            self.file_progress.emit(path, 0, "Analysiere")
            mi = analyze_media(path, self.tools)
            if self.abort_requested:
                raise _UserAbortError("Abgebrochen")
            probe = self._run_json_ffprobe(path)
            if self.abort_requested:
                raise _UserAbortError("Abgebrochen")
            primary = mi.primary_video
            if primary is None:
                raise RuntimeError(f"{Path(path).name}: Kein Primärvideo gefunden.")

            fmt = probe.get("format", {}) or {}
            streams = list(probe.get("streams", []) or [])
            video_stream = next((s for s in streams if s.get("codec_type") == "video"), {})
            format_names = str(fmt.get("format_name") or "").lower()
            suffix_container = _container_from_path(path)
            probed_container = _container_from_format_name(format_names)
            effective_container = probed_container if probed_container != "unknown" else suffix_container
            analysis_warnings = list(getattr(mi, "analysis_warnings", []) or [])
            if probed_container != "unknown" and suffix_container != "unknown" and probed_container != suffix_container:
                analysis_warnings.append(
                    f"Containerabweichung erkannt: Dateiendung={suffix_container}, ffprobe={probed_container}"
                )
                effective_container = probed_container
            fps = _parse_fps(str(video_stream.get("avg_frame_rate") or video_stream.get("r_frame_rate") or ""))

            info = {
                "path": path,
                "container": effective_container,
                "container_from_suffix": suffix_container,
                "container_from_probe": probed_container,
                "format_name": format_names,
                "video_codec": (primary.codec or "").lower(),
                "width": int(primary.width or 0),
                "height": int(primary.height or 0),
                "fps": fps,
                "audio_structure": _audio_signature(list(mi.audio_streams or [])),
                "subtitle_structure": _subtitle_signature(list(mi.subtitle_streams or [])),
                "analysis_warnings": analysis_warnings,
            }
            infos.append(info)

            self._log(
                f"Analyse {index}/{total}: {Path(path).name} | "
                f"{info['container']} | {info['video_codec']} | "
                f"{info['width']}x{info['height']} | FPS={info['fps'] if info['fps'] is not None else 'unbekannt'}"
            )
            for warning in info["analysis_warnings"]:
                self._log(f"Analysewarnung {Path(path).name}: {warning}", "warn")

            pct = min(30, int(index / total * 30))
            self.file_progress.emit(path, pct, info)
            self.progress.emit(pct)

        return infos

    def _check_lossless_merge_possible(
        self,
        infos: list[dict[str, Any]],
        target_container: str,
    ) -> tuple[bool, list[str]]:
        reasons: list[str] = []
        if len(infos) < 2:
            reasons.append("Mindestens zwei Eingaben erforderlich.")
            return False, reasons

        if target_container != "mkv":
            reasons.append(f"Zielcontainer '.{target_container}' wird für Merge nicht unterstützt.")
            return False, reasons

        containers = {str(info["container"]).lower() for info in infos}
        if containers != {"mkv"}:
            reasons.append("Lossless MKV-Merge erlaubt nur reine MKV-Eingaben.")

        first = infos[0]
        for info in infos[1:]:
            if info["video_codec"] != first["video_codec"]:
                reasons.append("Videocodec ist nicht in allen Dateien identisch.")
                break
        for info in infos[1:]:
            if (info["width"], info["height"]) != (first["width"], first["height"]):
                reasons.append("Auflösung ist nicht in allen Dateien identisch.")
                break
        for info in infos[1:]:
            if info["fps"] != first["fps"]:
                reasons.append("FPS ist nicht in allen Dateien identisch.")
                break
        for info in infos[1:]:
            if info["audio_structure"] != first["audio_structure"]:
                reasons.append("Audio-Struktur ist nicht in allen Dateien identisch.")
                break
        for info in infos[1:]:
            if info["subtitle_structure"] != first["subtitle_structure"]:
                reasons.append("Untertitel-Struktur ist nicht in allen Dateien identisch.")
                break

        ok = not reasons
        return ok, reasons

    def _build_merge_plan(
        self,
        infos: list[dict[str, Any]],
        output_path: str,
        mode: str,
    ) -> dict[str, Any]:
        target_container = _container_from_path(output_path)
        lossless_possible, reasons = self._check_lossless_merge_possible(infos, target_container)
        return {
            "mode": mode,
            "target_container": target_container,
            "tool": "mkvmerge",
            "lossless_possible": lossless_possible,
            "reasons": reasons,
            "infos": infos,
            "files": [info["path"] for info in infos],
            "output_path": output_path,
        }

    def _run_lossless_merge(self, plan: dict[str, Any]) -> bool:
        container = plan["target_container"]
        files = list(plan["files"])
        output_path = str(plan["output_path"])

        self._logger.file_start(
            1,
            1,
            output_path,
            "merge",
            None,
            "lossless",
            plan["tool"],
            q_label="Modus",
        )
        self.progress.emit(50)
        self.file_progress.emit(output_path, 50, "Merge läuft")

        if container == "mkv":
            return self._merge_mkv_lossless(files, output_path)

        self._log(f"Kein lossless Merge-Pfad für '.{container}' vorhanden.", "error")
        return False

    def _merge_mkv_lossless(self, files: list[str], output_path: str) -> bool:
        out = Path(output_path)
        tmp_out = out.with_name(f"{out.name}.__merge_tmp__")
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            if tmp_out.exists():
                tmp_out.unlink()
        except Exception as exc:
            self._log(f"Temporäre Merge-Datei konnte nicht entfernt werden ({tmp_out.name}): {exc}", "error")
            return False

        cmd = [self.tools.mkvmerge, "-o", str(tmp_out), files[0]]
        for path in files[1:]:
            cmd += ["+", path]

        self._log(f"Starte lossless MKV-Merge mit mkvmerge: {out.name}")
        start_ts = time.time()
        total_before = 0
        for path in files:
            try:
                total_before += Path(path).stat().st_size
            except Exception:
                pass

        def cleanup_partial_output() -> None:
            if not tmp_out.exists():
                return
            try:
                tmp_out.unlink()
                self._log(f"Partielle temporäre Merge-Datei entfernt: {tmp_out.name}", "warn")
            except Exception as exc:
                self._log(f"Cleanup-Warnung für temporäre Merge-Datei {tmp_out.name}: {exc}", "warn")

        try:
            result = run_tool(
                cmd,
                label="mkvmerge",
                timeout_s=get_timeout("worker_media_process"),
                timeout_mode="inactivity",
                worker=self,
                log=self._log,
                merge_stderr=True,
                stdout_line=lambda line: self._log(f"mkvmerge: {line}") if line.strip() else None,
            )
            if result.aborted:
                raise _UserAbortError("Abgebrochen")
            if result.timed_out:
                self._log("mkvmerge wurde wegen Inaktivitäts-Timeout abgebrochen.", "error")
                cleanup_partial_output()
                return False
            if not result.ok:
                self._log(f"mkvmerge fehlgeschlagen (Exitcode {result.returncode}).", "error")
                cleanup_partial_output()
                return False

            if not tmp_out.exists() or tmp_out.stat().st_size <= 0:
                self._log("mkvmerge lieferte keine gültige Ausgabedatei.", "error")
                cleanup_partial_output()
                return False

            if out.exists() and out.resolve() != tmp_out.resolve():
                self._log(
                    f"Zieldatei existiert bereits und wird nicht überschrieben: {out.name}",
                    "error",
                )
                cleanup_partial_output()
                return False

            try:
                os.replace(str(tmp_out), str(out))
            except Exception as exc:
                self._log(f"Finales Ersetzen der Zieldatei fehlgeschlagen: {exc}", "error")
                cleanup_partial_output()
                return False

            self._logger.file_done(
                files[0],
                str(out),
                total_before,
                out.stat().st_size,
                time.time() - start_ts,
                overwritten=False,
                start_ts=start_ts,
            )
            self._log("Lossless MKV-Merge erfolgreich abgeschlossen.", "success")
            return True
        except _UserAbortError:
            cleanup_partial_output()
            raise
