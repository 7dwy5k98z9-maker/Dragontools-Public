# -*- coding: utf-8 -*-
"""QThread-Worker für Extraktion, Injection und Untertitelkonvertierung."""
from __future__ import annotations

import threading
import traceback
from pathlib import Path

from PyQt6.QtCore import QThread, pyqtSignal

from ..core.lang_codes import lang_iso_tag
from ..core.tool_paths import ToolPaths
from ..worker.process_control import terminate_process_tree
from ..worker.tool_runner import run_tool
from ..subtitle.extractor import extract_with_ffmpeg, extract_to_mks_with_mkvmerge
from ..subtitle.formats import subtitle_extraction_targets, subtitle_codec_is_text, normalize_subtitle_codec
from ..subtitle.media_verification import probe_streams
from ..subtitle.sidecar_matcher import find_injection_subtitle
from ..subtitle.injector import inject_with_mkvmerge, inject_with_ffmpeg
from ..subtitle.converter import build_ass_style, srt_to_ass, subtitle_to_txt, txt_to_ass, txt_to_srt

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
                    stream_index = s.get("index")
                    if type(stream_index) is not int or stream_index < 0:
                        self.log.emit("  ❌ Untertitelspur ohne gültigen FFprobe-Index übersprungen")
                        continue
                    codec = normalize_subtitle_codec(s.get("codec_name"), s.get("codec_tag_string"))
                    lang = lang_iso_tag((s.get("tags") or {}).get("language", "und"))
                    attempts = subtitle_extraction_targets(codec, s.get("codec_tag_string"))
                    ok = False
                    used_out: Path | None = None
                    for attempt_no, target in enumerate(attempts, start=1):
                        out = _unique_output_path(
                            Path(self.out_dir)
                            / f"{Path(path).stem}.{lang}.{stream_index}{target.suffix}"
                        )
                        if attempt_no > 1:
                            self.log.emit(
                                f"  ↪️ Stream {stream_index} ({codec}): versuche {target.description}"
                            )
                        ok = extract_with_ffmpeg(
                            path, stream_index, str(out), self.tools.ffmpeg,
                            logger=self.log.emit, codec_args=list(target.codec_args), worker=self,
                        )
                        if ok:
                            used_out = out
                            break
                    if not ok:
                        # Final generic fallback: let MKVToolNix map the FFprobe
                        # stream ordinal to its own track ID and keep the subtitle
                        # losslessly in an .mks container.  This also covers codecs
                        # unknown to DragonTools' format table.
                        out = _unique_output_path(
                            Path(self.out_dir) / f"{Path(path).stem}.{lang}.{stream_index}.mks"
                        )
                        self.log.emit(
                            f"  ↪️ Stream {stream_index} ({codec}): versuche MKVToolNix-Verlustfrei-Fallback"
                        )
                        ok = extract_to_mks_with_mkvmerge(
                            path, stream_index, str(out),
                            mkvmerge=self.tools.mkvmerge,
                            ffprobe=self.tools.ffprobe,
                            logger=self.log.emit,
                            worker=self,
                        )
                        if ok:
                            used_out = out
                    if ok and used_out is not None:
                        self.log.emit(f"  ✅ Stream {stream_index} ({codec}) → {used_out.name}")
                    else:
                        self.log.emit(
                            f"  ❌ Stream {stream_index} ({codec}) konnte mit keinem verfügbaren Backend extrahiert werden"
                        )
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
                 language: str, forced: bool, tools: ToolPaths, title: str = "Deutsch"):
        super().__init__()
        self.video_files = video_files
        self.title       = title
        self.sub_file    = sub_file
        self.language    = language
        self.forced      = forced
        self.tools       = tools

    def _output_path(self, video_path: str, *, force_mkv: bool = False) -> str:
        p = Path(video_path)
        if force_mkv:
            candidate = p.with_name(p.stem + "_sub.mkv")
        elif p.suffix.lower() in {".mkv", ".mp4", ".m4v", ".mov"}:
            candidate = p.with_stem(p.stem + "_sub")
        else:
            candidate = p.with_name(p.stem + "_sub.mkv")
        return str(_unique_output_path(candidate))

    def _probe_subtitle_codec(self, sub_file: str) -> str:
        rows = probe_streams(
            sub_file, ffprobe=self.tools.ffprobe, worker=self, logger=self.log.emit
        )
        subtitles = [row for row in rows if row.get("codec_type") == "subtitle"]
        forbidden = [row for row in rows if row.get("codec_type") in {"video", "audio"}]
        if len(subtitles) != 1 or forbidden:
            raise ValueError("Die Zusatzdatei muss genau eine Untertitelspur und keine Audio-/Videospur enthalten.")
        row = subtitles[0]
        return normalize_subtitle_codec(row.get("codec_name"), row.get("codec_tag_string"))

    def run(self) -> None:
        try:
            total = len(self.video_files)
            for idx, path in enumerate(self.video_files):
                if self._cancel:
                    break
                self.log.emit(f"▶ Einfügen in: {Path(path).name}")
                try:
                    sub_file = self.sub_file or str(find_injection_subtitle(path, self.language))
                except (ValueError, OSError) as exc:
                    self.log.emit(f"  ⚠️ Übersprungen: {exc}")
                    self.progress.emit(idx + 1, total)
                    continue
                self.log.emit(f"  Untertitel: {Path(sub_file).name} | {self.language} | {self.title}")
                try:
                    subtitle_codec = self._probe_subtitle_codec(sub_file)
                except Exception as exc:
                    self.log.emit(f"  ❌ Untertitel-Datei nicht eindeutig erkannt: {exc}")
                    self.progress.emit(idx + 1, total)
                    continue

                video_suffix = Path(path).suffix.lower()
                ok = False

                # MP4/MOV können nicht alle Untertitelcodecs darstellen. Text wird
                # wie bisher als mov_text eingefügt; Bitmap/binäre/ unbekannte Subs
                # wechseln automatisch auf MKV statt die Spur zu verwerfen.
                if video_suffix in {".mp4", ".m4v", ".mov"} and subtitle_codec_is_text(subtitle_codec):
                    out = self._output_path(path)
                    ok = inject_with_ffmpeg(
                        path, sub_file, out,
                        self.language, self.tools.ffmpeg,
                        logger=self.log.emit,
                        subtitle_codec="mov_text",
                        map_existing_subtitles=True,
                        worker=self,
                        forced=self.forced,
                        ffprobe=self.tools.ffprobe,
                        title=self.title,
                    )
                    if not ok:
                        self.log.emit(
                            "  ↪️ MP4/MOV-Mux nicht möglich; versuche verlustfrei als MKV."
                        )
                        out = self._output_path(path, force_mkv=True)
                        ok = inject_with_mkvmerge(
                            path, sub_file, out,
                            self.language, self.forced,
                            logger=self.log.emit,
                            mkvmerge=self.tools.mkvmerge,
                            ffprobe=self.tools.ffprobe,
                            title=self.title,
                            worker=self,
                        )
                else:
                    force_mkv = video_suffix not in {".mkv"} or not subtitle_codec_is_text(subtitle_codec)
                    out = self._output_path(path, force_mkv=force_mkv)
                    if force_mkv and video_suffix in {".mp4", ".m4v", ".mov"}:
                        self.log.emit(
                            f"  ℹ️ Codec {subtitle_codec} ist für MP4/MOV nicht verlustfrei geeignet; Ausgabe wird MKV."
                        )
                    ok = inject_with_mkvmerge(
                        path, sub_file, out,
                        self.language, self.forced,
                        logger=self.log.emit,
                        mkvmerge=self.tools.mkvmerge,
                        ffprobe=self.tools.ffprobe,
                        title=self.title,
                        worker=self,
                    )
                    if not ok:
                        ok = inject_with_ffmpeg(
                            path, sub_file, out,
                            self.language, self.tools.ffmpeg,
                            logger=self.log.emit,
                            worker=self,
                            forced=self.forced,
                            ffprobe=self.tools.ffprobe,
                            title=self.title,
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
    def __init__(
        self, files: list[str], mode: str, out_dir: str,
        *, font_family: str = "Arial", font_size: int = 22,
    ):
        super().__init__()
        self.files   = files
        self.mode    = mode    # "srt2ass" | "sub2txt" | "txt2srt" | "txt2ass"
        self.out_dir = out_dir
        self.font_family = str(font_family or "Arial")
        self.font_size = max(8, min(200, int(font_size)))

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
                        out = str(_unique_output_path(Path(self.out_dir) / (Path(path).stem + ".ass")))
                        srt_to_ass(path, out, style=build_ass_style(self.font_family, self.font_size))
                    elif self.mode == "txt2srt":
                        if Path(path).suffix.lower() != ".txt":
                            raise ValueError("TXT -> SRT unterstützt nur .txt-Dateien.")
                        out = str(_unique_output_path(Path(self.out_dir) / (Path(path).stem + ".srt")))
                        txt_to_srt(path, out)
                        self.log.emit(
                            f"  ℹ️ SRT speichert keine Schriftart/-größe; Vorschau: "
                            f"{self.font_family}, {self.font_size} px"
                        )
                    elif self.mode == "txt2ass":
                        if Path(path).suffix.lower() != ".txt":
                            raise ValueError("TXT -> ASS unterstützt nur .txt-Dateien.")
                        out = str(_unique_output_path(Path(self.out_dir) / (Path(path).stem + ".ass")))
                        txt_to_ass(path, out, style=build_ass_style(self.font_family, self.font_size))
                    else:
                        out = str(_unique_output_path(Path(self.out_dir) / (Path(path).stem + ".txt")))
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
