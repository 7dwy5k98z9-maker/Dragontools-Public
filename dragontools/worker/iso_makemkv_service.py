# -*- coding: utf-8 -*-
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from ..core.timeout_settings import get_timeout
from ..core.move_transaction import publish_staged_no_replace
from .iso_disc_inspector import ISODiscInspector
from .iso_title_parser import parse_makemkv_titles
from .iso_models import ISOExtractionResult, ISOScanResult, ISOUserAbortError
from .tool_runner import run_tool
from .output_verifier import OutputVerifier
from .iso_output_publication import ISOExtractionWorkspace, publish_iso_titles
from ..core.callback_dispatch import best_effort_callback

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
        self._title_durations = {}

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
        if result.timed_out:
            raise RuntimeError('MakeMKV wurde wegen Zeitüberschreitung beendet.')
        return result.returncode, lines

    def scan_titles(self, path: str, *, run_makemkv: RunMakeMKVFn) -> ISOScanResult:
        source = self._inspector.makemkv_source(path)
        self._title_durations.pop(str(Path(path).resolve()), None)
        rc, lines = run_makemkv(["-r", "--cache=1", "info", source], progress_path=path)
        if isinstance(rc, bool) or not isinstance(rc, int) or rc != 0:
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

        result = parse_makemkv_titles(lines)
        self._title_durations[str(Path(path).resolve())] = {row["id"]: row["duration"] for row in result}
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

        if any(type(title_id) is not int or title_id < 0 for title_id in title_ids):
            return ISOExtractionResult(ok=False, error="Ungültige MakeMKV-Titel-ID.")
        selected = list(dict.fromkeys(title_ids))

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        source = self._inspector.makemkv_source(path)
        selection = ", ".join(str(title_id) for title_id in selected)
        self._log(f"ℹ️ Extrahiere Titel {selection} transaktional nach {out_dir}", "info")
        self._progress(path, 35, selected)
        total_titles = max(1, len(selected))

        # MakeMKV chooses its own output names. Extract into a private sibling
        # directory so partial/malformed results are never visible under the
        # user's final destination names before all selected titles succeeded.
        workspace = ISOExtractionWorkspace(out_dir, self._log)
        with workspace as temp_root:
            stage_dir = Path(temp_root)
            staged_title_ids = {}
            for offset, title_id in enumerate(selected, start=1):
                previous_files = set(stage_dir.glob("*.mkv"))
                self._log(f"ℹ️ MakeMKV-Titel {title_id} ({offset}/{total_titles})", "info")
                rc, lines = run_makemkv(
                    ["-r", "--cache=1", "mkv", source, str(title_id), str(stage_dir)],
                    progress_path=path,
                )
                if isinstance(rc, bool) or not isinstance(rc, int) or rc != 0:
                    detail = "\n".join(lines[-8:]).strip()
                    error = f"MakeMKV-Extraktion von Titel {title_id} fehlgeschlagen (Exitcode {rc})."
                    if detail:
                        error += f"\n{detail}"
                    self._log(f"❌ {error}", "error")
                    return ISOExtractionResult(ok=False, error=error)
                created = set(stage_dir.glob("*.mkv")) - previous_files
                if len(created) != 1:
                    return ISOExtractionResult(ok=False, error="MakeMKV erzeugte aber nicht genau eine neue MKV für den ausgewählten Titel.")
                staged_title_ids[next(iter(created))] = title_id
                self._progress(path, 35 + int(offset / total_titles * 45), selected)

            staged_files = sorted(stage_dir.glob("*.mkv"), key=lambda file: file.name)
            if len(staged_files) != len(selected):
                error = (
                    "MakeMKV meldete Erfolg, erzeugte aber nicht genau eine MKV pro ausgewähltem Titel: "
                    f"erwartet {len(selected)}, gefunden {len(staged_files)}."
                )
                self._log(f"❌ {error}", "error")
                return ISOExtractionResult(ok=False, error=error)

            verifier = OutputVerifier(
                worker=self._worker,
                ffprobe_path=str(getattr(self._tools, "ffprobe", "") or ""),
                min_size_bytes=1024,
            )
            for staged in staged_files:
                duration = self._title_durations.get(str(Path(path).resolve()), {}).get(staged_title_ids[staged], 0)
                verification = verifier.verify(str(staged), "mkv", source_has_audio=False,
                    expected_duration_ms=(duration * 1000 if duration > 0 else None))
                if not verification.ok:
                    detail = "; ".join(verification.messages or []) or "unbekannter Verifikationsfehler"
                    error = f"MakeMKV-Ausgabe {staged.name} ist ungültig: {detail}"
                    self._log(f"❌ {error}", "error")
                    return ISOExtractionResult(ok=False, error=error)
                workspace.mark_verified(staged)

            destinations = [out_dir / staged.name for staged in staged_files]
            occupied = [dest.name for dest in destinations if dest.exists()]
            if occupied:
                error = "MakeMKV-Zieldatei(en) existieren bereits und werden nicht überschrieben: " + ", ".join(occupied)
                self._log(f"❌ {error}", "error")
                return ISOExtractionResult(ok=False, error=error)

            try:
                publish_iso_titles(staged_files, destinations, receipts=workspace.verified,
                    worker=self._worker, publish=publish_staged_no_replace)
            except Exception as exc:
                error = f"MakeMKV-Ausgaben konnten nicht atomar veröffentlicht werden: {exc}"
                self._log(f"❌ {error}", "error")
                return ISOExtractionResult(ok=False, error=error)

            workspace.published = True
            final_files = [str(destination) for destination in destinations]
            best_effort_callback(self._progress, path, 90, selected)
            best_effort_callback(self._log,
                f"ℹ️ {len(final_files)} MKV-Datei(en) extrahiert und verifiziert: "
                + ", ".join(Path(file).name for file in final_files),
                "info",
            )
            best_effort_callback(self._log, "✅ MakeMKV-Extraktion erfolgreich abgeschlossen.", "info")
            return ISOExtractionResult(ok=True, extracted_files=final_files)
