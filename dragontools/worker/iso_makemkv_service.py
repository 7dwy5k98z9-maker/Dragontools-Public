# -*- coding: utf-8 -*-
from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Callable

from ..core.timeout_settings import get_timeout
from .iso_disc_inspector import ISODiscInspector, parse_duration_to_seconds, parse_size_to_bytes
from .iso_models import ISOExtractionResult, ISOScanResult, ISOUserAbortError
from .tool_runner import run_tool

ProgressFn = Callable[[str, int, object], None]
RunMakeMKVFn = Callable[[list[str], str | None], tuple[int, list[str]]]


def tool_exists(path: str) -> bool:
    text = (path or "").strip()
    if not text:
        return False
    try:
        return Path(text).is_file() or shutil.which(text) is not None
    except (OSError, ValueError):
        return False


class ISOMakeMKVService:
    """MakeMKV execution, title parsing and title extraction."""

    def __init__(self, *, tools, inspector: ISODiscInspector, worker, log, progress: ProgressFn) -> None:
        self._tools = tools
        self._inspector = inspector
        self._worker = worker
        self._log = log
        self._progress = progress

    def ensure_tool(self) -> str:
        tool = getattr(self._tools, "makemkvcon", "") or ""
        if not tool_exists(tool):
            raise RuntimeError("MakeMKV CLI (makemkvcon) wurde nicht gefunden.")
        return tool

    def available(self) -> bool:
        return tool_exists(getattr(self._tools, "makemkvcon", "") or "")

    def run(self, args: list[str], progress_path: str | None = None) -> tuple[int, list[str]]:
        exe = self.ensure_tool()
        cmd = [exe] + args
        self._log("▶ " + " ".join(cmd), "info")
        lines: list[str] = []

        def _line(raw: str) -> None:
            line = raw.rstrip()
            lines.append(line)
            if line:
                self._log(line, "info")
                if progress_path:
                    self._progress(progress_path, 5, None)

        result = run_tool(
            cmd,
            label="MakeMKV",
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

    def scan_titles(self, path: str, *, run_makemkv: RunMakeMKVFn) -> ISOScanResult:
        source = self._inspector.makemkv_source(path)
        rc, lines = run_makemkv(["-r", "--cache=1", "info", source], progress_path=path)
        if rc != 0:
            self._log(f"❌ MakeMKV-Scan fehlgeschlagen (Exitcode {rc}).", "info")
            joined = "\n".join(lines).lower()
            if "programmversion ist zu alt" in joined or "program version is too old" in joined:
                error = (
                    "MakeMKV ist zu alt und muss aktualisiert werden. "
                    "Die ISO wurde erkannt, aber MakeMKV hat die Analyse vor der Titelsuche beendet."
                )
            elif any(word in joined for word in ("evaluation period", "license", "lizenz", "freigeschaltet")):
                error = (
                    "MakeMKV ist nicht freigeschaltet oder verlangt eine Lizenz/Testlizenz. "
                    "Der optionale FFmpeg-Fallback kann nur unverschlüsselte, direkt lesbare Strukturen versuchen."
                )
            else:
                error = f"MakeMKV-Scan fehlgeschlagen (Exitcode {rc})."
            return ISOScanResult(error=error)

        titles: dict[int, dict] = {}
        title_re = re.compile(r'^TINFO:(\d+),(\d+),\d+,"?(.*?)"?$')
        for line in lines:
            match = title_re.match(line)
            if not match:
                continue
            title_id = int(match.group(1))
            code = int(match.group(2))
            raw = match.group(3).strip().strip('"')
            entry = titles.setdefault(
                title_id,
                {"id": title_id, "duration": 0, "size": 0, "name": f"Title {title_id}"},
            )
            if code == 2 and raw:
                entry["name"] = raw
            elif code == 8 and raw:
                entry["duration"] = parse_duration_to_seconds(raw)
            elif code == 11 and raw:
                entry["size"] = parse_size_to_bytes(raw)

        result = [titles[key] for key in sorted(titles)]
        if result:
            self._log(f"ℹ️ {len(result)} Titel gefunden.", "info")
        else:
            self._log("⚠️ MakeMKV-Scan lieferte keine verwertbaren Titelinformationen.", "info")
        return ISOScanResult(titles=result)

    def extract_titles(
        self,
        path: str,
        title_ids: list[int],
        output_dir: str,
        *,
        run_makemkv: RunMakeMKVFn,
    ) -> ISOExtractionResult:
        if not title_ids:
            self._log("⚠️ Keine Titel zur Extraktion angegeben.", "info")
            return ISOExtractionResult(ok=False, error="Keine Titel zur Extraktion angegeben.")

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        source = self._inspector.makemkv_source(path)
        before: set[Path] = set(out_dir.glob("*.mkv"))

        selection = ", ".join(str(title_id) for title_id in title_ids)
        self._log(f"ℹ️ Extrahiere Titel {selection} nach {out_dir}", "info")
        self._progress(path, 35, title_ids)
        total_titles = max(1, len(title_ids))
        for offset, title_id in enumerate(title_ids, start=1):
            self._log(f"ℹ️ MakeMKV-Titel {title_id} ({offset}/{total_titles})", "info")
            rc, _lines = run_makemkv(
                ["-r", "--cache=1", "mkv", source, str(title_id), str(out_dir)],
                progress_path=path,
            )
            if rc != 0:
                self._log(f"❌ MakeMKV-Extraktion von Titel {title_id} fehlgeschlagen (Exitcode {rc}).", "info")
                return ISOExtractionResult(ok=False, error=f"MakeMKV-Extraktion fehlgeschlagen (Exitcode {rc}).")
            self._progress(path, 35 + int(offset / total_titles * 55), title_ids)

        after: set[Path] = set(out_dir.glob("*.mkv"))
        new_files = sorted(after - before, key=lambda file: file.name)
        if new_files:
            self._log(
                f"ℹ️ {len(new_files)} MKV-Datei(en) extrahiert: {', '.join(file.name for file in new_files)}",
                "info",
            )
        self._log("✅ MakeMKV-Extraktion erfolgreich abgeschlossen.", "info")
        return ISOExtractionResult(ok=True, extracted_files=[str(file) for file in new_files])
