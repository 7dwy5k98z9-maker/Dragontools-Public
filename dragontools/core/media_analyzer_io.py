# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import traceback
from pathlib import Path

from .paths import ToolPaths
from .process_runner import run_analysis_tool as _run_tool
from .type_utils import _safe_int

def _run_mediainfo_json(path: str, tools: ToolPaths) -> tuple[dict, list[str], bool]:
    """Führt MediaInfo aus und gibt (json_dict, warnings, mi_found) zurück.

    mi_found=True  : MediaInfo-Executable wurde gefunden und gestartet
    mi_found=False : Executable nicht vorhanden oder nicht erreichbar
    """
    warnings: list[str] = []
    mi_exe = getattr(tools, "mediainfo", None)

    # Executable-Prüfung: entweder absoluter Pfad existiert nicht,
    # oder der Eintrag ist leer → nicht gefunden
    exe_str = str(mi_exe) if mi_exe else ""
    exe_path = Path(exe_str) if exe_str else None
    if not exe_str or (exe_path and exe_path.is_absolute() and not exe_path.exists()):
        warnings.append("MediaInfo nicht gefunden")
        return {}, warnings, False

    try:
        result = _run_tool([exe_str, "--Output=JSON", path])
        data = json.loads(result.stdout or "{}")
        return data, warnings, True
    except Exception as e:
        warnings.append(f"MediaInfo-Analyse fehlgeschlagen: {e}")
        warnings.append(traceback.format_exc())
        return {}, warnings, True   # Executable war da, hat aber versagt

def _run_ffprobe_json(path: str, tools: ToolPaths) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    try:
        result = _run_tool([
            tools.ffprobe,
            "-v", "error",
            "-show_streams",
            "-show_format",
            "-of", "json",
            path,
        ])
        return json.loads(result.stdout or "{}"), warnings
    except Exception as e:
        warnings.append(f"ffprobe-Analyse fehlgeschlagen: {e}")
        warnings.append(traceback.format_exc())
        return {}, warnings

def _mi_tracks(mi_json: dict) -> list[dict]:
    media = mi_json.get("media", {}) or {}
    return media.get("track", []) or []

def _mi_general_track(mi_json: dict) -> dict:
    for tr in _mi_tracks(mi_json):
        if (tr.get("@type") or "").lower() == "general":
            return tr
    return {}

def _mi_video_tracks(mi_json: dict) -> list[dict]:
    return [tr for tr in _mi_tracks(mi_json) if (tr.get("@type") or "").lower() == "video"]

def _mi_audio_tracks(mi_json: dict) -> list[dict]:
    return [tr for tr in _mi_tracks(mi_json) if (tr.get("@type") or "").lower() == "audio"]

def _mi_text_tracks(mi_json: dict) -> list[dict]:
    return [tr for tr in _mi_tracks(mi_json) if (tr.get("@type") or "").lower() == "text"]

def _fp_streams_by_type(fp_json: dict, stream_type: str) -> list[dict]:
    streams = fp_json.get("streams", []) or []
    return [s for s in streams if (s.get("codec_type") or "").lower() == stream_type]

def _mi_bitrate(track: dict) -> int | None:
    for key in ("BitRate", "BitRate_Nominal", "OverallBitRate"):
        value = track.get(key)
        if value is None:
            continue
        try:
            return int(float(str(value).replace(" ", "")))
        except Exception:
            continue
    return None

def _mi_forced(track: dict) -> bool:
    """Liest das Forced-Flag aus einem MediaInfo-Track-Dict."""
    return (track.get("Forced") or "").strip().lower() == "yes"

def _mi_stream_index(track: dict, fallback: int) -> int:
    """Liest den Container-Stream-Index aus MediaInfo (StreamOrder = 0-basiert)."""
    return _safe_int(track.get("StreamOrder"), fallback)

def _mi_codec_audio(track: dict) -> str:
    """Normalisiert MediaInfo Audio-Format auf ffprobe-konforme Kleinschreibung."""
    fmt = (track.get("Format") or "").strip()
    mapping = {
        "E-AC-3": "eac3", "AC-3": "ac3", "AAC": "aac", "DTS": "dts",
        "TrueHD": "truehd", "Opus": "opus", "Vorbis": "vorbis",
        "FLAC": "flac", "MP3": "mp3", "PCM": "pcm",
    }
    return mapping.get(fmt, fmt.lower())
