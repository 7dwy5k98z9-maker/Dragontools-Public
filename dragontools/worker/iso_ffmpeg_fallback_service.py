# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

from ..core.timeout_settings import get_timeout
from .iso_disc_inspector import ISODiscInspector, quote_concat_path
from .iso_makemkv_service import tool_exists
from .iso_models import ISOExtractionResult, ISOUserAbortError
from .tool_runner import run_tool

ProgressFn = Callable[[str, int, object], None]
RunFFmpegFn = Callable[[list[str], str | None], tuple[int, list[str]]]


class ISOFFmpegFallbackService:
    """Lossless FFmpeg fallback for directly readable, unencrypted disc data."""

    def __init__(self, *, tools, inspector: ISODiscInspector, worker, log, progress: ProgressFn) -> None:
        self._tools = tools
        self._inspector = inspector
        self._worker = worker
        self._log = log
        self._progress = progress

    def ensure_ffmpeg(self) -> str:
        tool = getattr(self._tools, "ffmpeg", "") or ""
        if not tool_exists(tool):
            raise RuntimeError("FFmpeg wurde fuer den ISO-Fallback nicht gefunden.")
        return tool

    def run(self, cmd: list[str], progress_path: str | None = None) -> tuple[int, list[str]]:
        self._log("▶ " + " ".join(cmd), "info")
        lines: list[str] = []

        def _line(raw: str) -> None:
            line = raw.rstrip()
            lines.append(line)
            if line:
                self._log(line, "info")
                if progress_path:
                    self._progress(progress_path, 45, None)

        result = run_tool(
            cmd,
            label="ISO FFmpeg-Fallback",
            timeout_s=get_timeout("worker_media_process"),
            timeout_mode="inactivity",
            worker=self._worker,
            log=self._log,
            merge_stderr=True,
            stdout_line=_line,
        )
        if result.aborted:
            raise ISOUserAbortError("Abgebrochen")
        return result.returncode, lines

    def extract(
        self,
        path: str,
        output_dir: str,
        *,
        run_ffmpeg: RunFFmpegFn | None = None,
    ) -> ISOExtractionResult:
        try:
            ffmpeg = self.ensure_ffmpeg()
        except (OSError, RuntimeError, ValueError) as exc:
            self._log(f"❌ {exc}", "error")
            return ISOExtractionResult(ok=False, error=str(exc))

        candidate, candidate_error = self._inspector.ffmpeg_fallback_candidate(path)
        if not candidate:
            error = candidate_error or "FFmpeg-Fallback nicht möglich: keine direkt lesbare ISO-/Disc-Struktur gefunden."
            self._log(f"❌ {error}", "error")
            return ISOExtractionResult(ok=False, error=error)

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        output = self._inspector.unique_fallback_output(path, out_dir)
        self._progress(path, 35, [0])
        self._log(
            "⚠️ FFmpeg-Fallback ist aktiv. "
            "Dieser Weg remuxt ohne Re-Encoding, ist aber bei Menüs, Playlists, Kapiteln, "
            "Untertiteln und verschlüsselten Discs fehleranfälliger als MakeMKV.",
            "warn",
        )

        temp_list: Path | None = None
        try:
            if candidate["mode"] == "concat":
                files = list(candidate.get("files") or [])
                if not files:
                    raise RuntimeError("DVD-Fallback ohne VOB-Dateien.")
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    suffix=".ffconcat.txt",
                    dir=str(out_dir),
                    delete=False,
                ) as handle:
                    temp_list = Path(handle.name)
                    for file in files:
                        handle.write(quote_concat_path(file) + "\n")
                cmd = [
                    ffmpeg, "-hide_banner", "-nostdin", "-y", "-fflags", "+genpts",
                    "-f", "concat", "-safe", "0", "-i", str(temp_list),
                    "-map", "0", "-c", "copy", "-map_metadata", "0", str(output),
                ]
            else:
                src = Path(candidate["path"])
                cmd = [
                    ffmpeg, "-hide_banner", "-nostdin", "-y", "-fflags", "+genpts",
                    "-i", str(src), "-map", "0", "-c", "copy", "-map_metadata", "0", str(output),
                ]

            runner = run_ffmpeg or self.run
            rc, lines = runner(cmd, progress_path=path)
            if rc != 0:
                detail = "\n".join(lines[-8:]).strip()
                error = f"FFmpeg-Fallback fehlgeschlagen (Exitcode {rc})." + (f"\n{detail}" if detail else "")
                self._log(f"❌ FFmpeg-Fallback fehlgeschlagen (Exitcode {rc}).", "error")
                return ISOExtractionResult(ok=False, error=error)
            if not output.exists() or output.stat().st_size <= 0:
                error = "FFmpeg-Fallback erzeugte keine gültige Ausgabedatei."
                self._log(f"❌ {error}", "error")
                return ISOExtractionResult(ok=False, error=error)

            self._progress(path, 95, [0])
            self._log(f"✅ FFmpeg-Fallback abgeschlossen: {output.name}", "success")
            return ISOExtractionResult(ok=True, extracted_files=[str(output)])
        except ISOUserAbortError:
            raise
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            error = f"FFmpeg-Fallback fehlgeschlagen: {exc}"
            self._log(f"❌ {error}", "error")
            return ISOExtractionResult(ok=False, error=error)
        finally:
            if temp_list is not None:
                try:
                    temp_list.unlink(missing_ok=True)
                except OSError:
                    pass
