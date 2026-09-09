# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

from ..core.formatting import format_binary_size

LogFn = Callable[[str, str], None]


def safe_name(path: str) -> str:
    try:
        return Path(path).name
    except Exception:
        return path


def parse_duration_to_seconds(value: str) -> int:
    text = (value or "").strip()
    if not text:
        return 0
    parts = text.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = parts
            return int(hours) * 3600 + int(minutes) * 60 + int(seconds)
        if len(parts) == 2:
            minutes, seconds = parts
            return int(minutes) * 60 + int(seconds)
        return int(float(text))
    except (TypeError, ValueError):
        return 0


def parse_size_to_bytes(value: str) -> int:
    text = (value or "").strip()
    if not text:
        return 0
    if text.isdigit():
        return int(text)
    match = re.match(r"^\s*([\d.,]+)\s*([kmgt]?b)?\s*$", text.lower())
    if not match:
        return 0
    number = match.group(1).replace(",", ".")
    unit = (match.group(2) or "b").lower()
    factor = {
        "b": 1,
        "kb": 1024,
        "mb": 1024**2,
        "gb": 1024**3,
        "tb": 1024**4,
    }.get(unit, 1)
    try:
        return int(float(number) * factor)
    except (TypeError, ValueError):
        return 0


def format_size(value: int) -> str:
    return format_binary_size(value, decimals=1)


def quote_concat_path(path: Path) -> str:
    text = str(path).replace("\\", "/").replace("'", "'\\''")
    return f"file '{text}'"


class ISODiscInspector:
    """Qt-independent ISO/disc structure detection and fallback selection."""

    def __init__(self, *, log: LogFn) -> None:
        self._log = log

    @staticmethod
    def disc_root_for_makemkv(path: Path) -> Path:
        if path.is_dir() and path.name.upper() in {"BDMV", "VIDEO_TS"}:
            return path.parent
        return path

    def makemkv_source(self, path: str) -> str:
        source = self.disc_root_for_makemkv(Path(path))
        prefix = "iso" if source.suffix.lower() in (".iso", ".img") else "file"
        return f"{prefix}:{source}"

    def detect_iso_type(self, path: str) -> str:
        p = Path(path)
        if p.is_dir():
            upper_name = p.name.upper()
            if upper_name == "BDMV":
                if (p / "index.bdmv").exists() or (p / "STREAM").exists() or (p / "PLAYLIST").exists():
                    self._log(f"ℹ️ {safe_name(path)} als direkt ausgewählter Blu-ray-BDMV-Ordner erkannt.", "info")
                    return "bluray"
            if upper_name == "VIDEO_TS":
                if any(p.glob("*.VOB")) or any(p.glob("*.IFO")):
                    self._log(f"ℹ️ {safe_name(path)} als direkt ausgewählter DVD-VIDEO_TS-Ordner erkannt.", "info")
                    return "dvd"
            if (p / "BDMV").exists():
                self._log(f"ℹ️ {safe_name(path)} als Blu-ray-Struktur erkannt.", "info")
                return "bluray"
            if (p / "VIDEO_TS").exists():
                self._log(f"ℹ️ {safe_name(path)} als DVD-Struktur erkannt.", "info")
                return "dvd"
        elif p.is_file() and p.suffix.lower() in (".iso", ".img"):
            name = p.stem.lower()
            if "bluray" in name or "blu-ray" in name or "bdmv" in name or ".bd" in name:
                self._log(f"ℹ️ {safe_name(path)} konservativ als Blu-ray-Image erkannt.", "info")
                return "bluray"
            if "dvd" in name or "video_ts" in name:
                self._log(f"ℹ️ {safe_name(path)} konservativ als DVD-Image erkannt.", "info")
                return "dvd"
            self._log(
                f"⚠️ {safe_name(path)} ist eine Image-Datei, aber Typ konnte vorab nicht sicher bestimmt werden. "
                "MakeMKV-Scan wird trotzdem versucht.",
                "info",
            )
            return "iso"
        self._log(f"⚠️ {safe_name(path)} ist keine unterstützte ISO-/Disc-Eingabe.", "info")
        return "unknown"

    def ffmpeg_fallback_candidate(self, path: str) -> tuple[dict | None, str | None]:
        p = Path(path)
        try:
            if p.is_dir():
                dvd_dir = p / "VIDEO_TS"
                if not dvd_dir.exists() and p.name.upper() == "VIDEO_TS":
                    dvd_dir = p
                if dvd_dir.exists():
                    candidate = self.dvd_vob_candidate(dvd_dir)
                    if candidate:
                        return candidate, None

                stream_dir = p / "BDMV" / "STREAM"
                if not stream_dir.exists() and p.name.upper() == "BDMV":
                    stream_dir = p / "STREAM"
                if stream_dir.exists():
                    streams = sorted(
                        [
                            file
                            for file in stream_dir.iterdir()
                            if file.is_file() and file.suffix.lower() in {".m2ts", ".mts"}
                        ],
                        key=lambda file: file.stat().st_size,
                        reverse=True,
                    )
                    if streams:
                        top = streams[0]
                        return {
                            "mode": "file",
                            "path": top,
                            "size": top.stat().st_size,
                            "label": f"Blu-ray-Stream {top.name}",
                        }, None

            if p.is_file() and p.suffix.lower() in {".iso", ".m2ts", ".mts", ".vob"}:
                return {
                    "mode": "file",
                    "path": p,
                    "size": p.stat().st_size,
                    "label": "direkt lesbare Datei/ISO",
                }, None
        except (OSError, ValueError) as exc:
            return None, f"FFmpeg-Fallback-Kandidat konnte nicht bestimmt werden: {exc}"
        return None, None

    @staticmethod
    def dvd_vob_candidate(dvd_dir: Path) -> dict | None:
        groups: dict[str, list[Path]] = {}
        for file in dvd_dir.iterdir():
            if not file.is_file():
                continue
            match = re.match(r"(?i)^(VTS_\d{2})_(\d)\.VOB$", file.name)
            if not match or int(match.group(2)) <= 0:
                continue
            groups.setdefault(match.group(1).upper(), []).append(file)

        best_key: str | None = None
        best_files: list[Path] = []
        best_size = 0
        for key, files in groups.items():
            ordered = sorted(files, key=lambda file: file.name)
            size = sum(file.stat().st_size for file in ordered)
            if size > best_size:
                best_key = key
                best_files = ordered
                best_size = size

        if not best_files:
            return None
        return {
            "mode": "concat",
            "files": best_files,
            "size": best_size,
            "label": f"DVD-VOB-Titelgruppe {best_key}",
        }

    @staticmethod
    def unique_fallback_output(input_path: str, output_dir: Path) -> Path:
        src = Path(input_path)
        stem = src.stem if src.is_file() else src.name
        if stem.upper() in {"BDMV", "VIDEO_TS"} and src.parent.name:
            stem = src.parent.name
        safe = re.sub(r'[<>:"/\\|?*]+', "_", stem).strip() or "ISO_Import"
        base = output_dir / f"{safe}_ffmpeg_fallback.mkv"
        if not base.exists():
            return base
        for idx in range(2, 1000):
            candidate = output_dir / f"{safe}_ffmpeg_fallback_{idx}.mkv"
            if not candidate.exists():
                return candidate
        raise RuntimeError(f"Kein freier FFmpeg-Fallback-Dateiname für {safe}")

    def fallback_titles(self, path: str) -> tuple[list[dict], str | None]:
        candidate, error = self.ffmpeg_fallback_candidate(path)
        if not candidate:
            return [], error
        self._log(
            "⚠️ FFmpeg-Fallback-Kandidat erkannt: "
            f"{candidate['label']} ({format_size(int(candidate.get('size') or 0))}). "
            "Dieser Weg ist weniger zuverlässig als MakeMKV.",
            "warn",
        )
        return [
            {
                "id": 0,
                "duration": 0,
                "size": int(candidate.get("size") or 0),
                "name": f"FFmpeg-Fallback: {candidate['label']}",
            }
        ], None


# Compatibility aliases for historical imports from iso_thread.
_safe_name = safe_name
_parse_duration_to_seconds = parse_duration_to_seconds
_parse_size_to_bytes = parse_size_to_bytes
_format_size = format_size
_quote_concat_path = quote_concat_path
