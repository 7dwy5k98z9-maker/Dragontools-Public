# -*- coding: utf-8 -*-
"""QThread-Worker für Extraktion, Injection und Untertitelkonvertierung."""
from __future__ import annotations

import os
import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.lang_codes import lang_iso_tag, sub_codec_to_ext_and_args
from ..core.paths import ToolPaths
from ..worker.process_control import terminate_process_tree
from ..worker.tool_runner import run_tool
from ..subtitle.extractor import extract_with_ffmpeg
from ..subtitle.injector import inject_with_mkvmerge, inject_with_ffmpeg
from ..subtitle.converter import srt_to_ass, subtitle_to_txt, txt_to_ass, txt_to_srt

def _unique_output_path(path: Path) -> Path:
    """Liefert einen freien Ausgabepfad, ohne vorhandene Nutzerdateien zu überschreiben."""
    if not path.exists():
        return path
    counter = 1
    while True:
        candidate = path.with_name(f"{path.stem}_{counter}{path.suffix}")
        if not candidate.exists():
            return candidate
        counter += 1


# ---------------------------------------------------------------------------
# Basis-Worker
# ---------------------------------------------------------------------------

class _SubWorker(QThread):
    log     = pyqtSignal(str)
    progress = pyqtSignal(int, int)   # done, total
    done    = pyqtSignal()
    error   = pyqtSignal(str)

    def cancel(self) -> None:
        self._cancel = True
        terminate_process_tree(
            self,
            self._process_lock,
            log=lambda msg, _level="info": self.log.emit(msg),
            attr_name="current_process",
            label=self.__class__.__name__,
        )

    def __init__(self):
        super().__init__()
        self._cancel = False
        self._process_lock = threading.RLock()
        self.current_process = None
        self._paused = False

    @property
    def abort_requested(self) -> bool:
        return self._cancel

    @property
    def abort_type(self) -> str | None:
        return "sofort" if self._cancel else None


# ---------------------------------------------------------------------------
# Extraktion-Worker
# ---------------------------------------------------------------------------

class _ExtractWorker(_SubWorker):
    def __init__(self, files: list[str], out_dir: str, tools: ToolPaths):
        super().__init__()
        self.files   = files
        self.out_dir = out_dir
        self.tools   = tools

    def run(self) -> None:
        try:
            total = len(self.files)
            for idx, path in enumerate(self.files):
                if self._cancel:
                    break
                self.log.emit(f"▶ Extrahiere: {Path(path).name}")
                # ffprobe für Subtitle-Tracks
                import json
                try:
                    probe = run_tool(
                        [self.tools.ffprobe, "-v", "error", "-show_streams",
                         "-select_streams", "s", "-of", "json", path],
                        label="Subtitle ffprobe",
                        timeout_s=30,
                        worker=self,
                        log=lambda msg, level="info": self.log.emit(msg),
                    )
                    if probe.aborted:
                        break
                    if not probe.ok:
                        raise RuntimeError(probe.tail(8) or f"ffprobe rc={probe.returncode}")
                    data = json.loads(probe.stdout or "{}")
                    streams = data.get("streams", [])
                except Exception as e:
                    self.log.emit(f"❌ ffprobe Fehler: {e}")
                    streams = []
    
                Path(self.out_dir).mkdir(parents=True, exist_ok=True)
                for s in streams:
                    codec = (s.get("codec_name") or "subrip").lower()
                    result = sub_codec_to_ext_and_args(codec)
                    if result is None:
                        self.log.emit(f"  ⚠️ Stream {s.get('index', '?')} übersprungen: Codec {codec} nicht unterstützt")
                        continue
                    ext, codec_args = result
                    lang  = lang_iso_tag((s.get("tags") or {}).get("language", "und"))
                    out = _unique_output_path(Path(self.out_dir) / f"{Path(path).stem}.{lang}.{s['index']}{ext}")
                    ok = extract_with_ffmpeg(
                        path, s["index"], str(out), self.tools.ffmpeg,
                        logger=self.log.emit, codec_args=codec_args, worker=self,
                    )
                    if ok:
                        self.log.emit(f"  ✅ → {Path(out).name}")
                    else:
                        self.log.emit(f"  ❌ Stream {s['index']} fehlgeschlagen")
                self.progress.emit(idx + 1, total)
            self.done.emit()
        except Exception:
            self.log.emit("❌ Unbehandelte Ausnahme in _ExtractWorker.run()")
            self.log.emit(traceback.format_exc())
            self.error.emit(traceback.format_exc())
            self.done.emit()

# ---------------------------------------------------------------------------
# Einfügen-Worker
# ---------------------------------------------------------------------------

class _InjectWorker(_SubWorker):
    def __init__(self, video_files: list[str], sub_file: str,
                 language: str, forced: bool, tools: ToolPaths):
        super().__init__()
        self.video_files = video_files
        self.sub_file    = sub_file
        self.language    = language
        self.forced      = forced
        self.tools       = tools

    def _output_path(self, video_path: str) -> str:
        p = Path(video_path)
        if p.suffix.lower() in {".mkv", ".mp4", ".m4v", ".mov"}:
            candidate = p.with_stem(p.stem + "_sub")
        else:
            candidate = p.with_name(p.stem + "_sub.mkv")
        return str(_unique_output_path(candidate))

    def run(self) -> None:
        try:
            total = len(self.video_files)
            for idx, path in enumerate(self.video_files):
                if self._cancel:
                    break
                self.log.emit(f"▶ Einfügen in: {Path(path).name}")
                out = self._output_path(path)
                video_suffix = Path(path).suffix.lower()
                sub_suffix = Path(self.sub_file).suffix.lower()
                ok = False

                if video_suffix in {".mp4", ".m4v", ".mov"}:
                    if sub_suffix not in {".srt", ".ass", ".ssa"}:
                        self.log.emit("  ⚠️ MP4/MOV unterstützt hier nur Text-Untertitel (.srt/.ass).")
                    else:
                        ok = inject_with_ffmpeg(
                            path, self.sub_file, out,
                            self.language, self.tools.ffmpeg,
                            logger=self.log.emit,
                            subtitle_codec="mov_text",
                            map_existing_subtitles=False,
                            worker=self,
                        )
                else:
                    ok = inject_with_mkvmerge(
                        path, self.sub_file, out,
                        self.language, self.forced,
                        logger=self.log.emit,
                        mkvmerge=self.tools.mkvmerge,
                        worker=self,
                    )
                    if not ok:
                        ok = inject_with_ffmpeg(
                            path, self.sub_file, out,
                            self.language, self.tools.ffmpeg,
                            logger=self.log.emit,
                            worker=self,
                        )
                self.log.emit("  ✅ OK" if ok else "  ❌ Fehler")
                self.progress.emit(idx + 1, total)
            self.done.emit()
        except Exception:
            self.log.emit("❌ Unbehandelte Ausnahme in _InjectWorker.run()")
            self.log.emit(traceback.format_exc())
            self.error.emit(traceback.format_exc())
            self.done.emit()
            
# ---------------------------------------------------------------------------
# Konvertierungs-Worker
# ---------------------------------------------------------------------------

class _ConvertWorker(_SubWorker):
    def __init__(self, files: list[str], mode: str, out_dir: str):
        super().__init__()
        self.files   = files
        self.mode    = mode    # "srt2ass" | "sub2txt" | "txt2srt" | "txt2ass"
        self.out_dir = out_dir

    def run(self) -> None:
        try:
            total = len(self.files)
            for idx, path in enumerate(self.files):
                if self._cancel:
                    break
                self.log.emit(f"▶ {Path(path).name}")
                try:
                    if self.mode == "srt2ass":
                        if Path(path).suffix.lower() != ".srt":
                            raise ValueError("SRT -> ASS unterstützt nur .srt-Dateien.")
                        out = os.path.join(self.out_dir, Path(path).stem + ".ass")
                        srt_to_ass(path, out)
                    elif self.mode == "txt2srt":
                        if Path(path).suffix.lower() != ".txt":
                            raise ValueError("TXT -> SRT unterstützt nur .txt-Dateien.")
                        out = os.path.join(self.out_dir, Path(path).stem + ".srt")
                        txt_to_srt(path, out)
                    elif self.mode == "txt2ass":
                        if Path(path).suffix.lower() != ".txt":
                            raise ValueError("TXT -> ASS unterstützt nur .txt-Dateien.")
                        out = os.path.join(self.out_dir, Path(path).stem + ".ass")
                        txt_to_ass(path, out)
                    else:
                        out = os.path.join(self.out_dir, Path(path).stem + ".txt")
                        subtitle_to_txt(path, out)
                    self.log.emit(f"  ✅ → {Path(out).name}")
                except Exception as e:
                    self.log.emit(f"  ❌ {e}")
                self.progress.emit(idx + 1, total)
            self.done.emit()
        except Exception:
            self.log.emit("❌ Unbehandelte Ausnahme in _ConvertWorker.run()")
            self.log.emit(traceback.format_exc())
            self.error.emit(traceback.format_exc())
            self.done.emit()
