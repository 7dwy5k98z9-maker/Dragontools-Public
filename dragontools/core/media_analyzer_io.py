# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import traceback

from .tool_paths import ToolPaths
from .process_runner import run_analysis_tool as _run_tool, tool_available
from .type_utils import _safe_bool, _safe_int

class AnalysisStoppedError(RuntimeError):
    """A worker stop must never trigger another analysis-tool fallback."""


def _run_mediainfo_json(path: str, tools: ToolPaths, *, run_process=None) -> tuple[dict, list[str], bool]:
    """Führt MediaInfo aus und gibt (json_dict, warnings, mi_found) zurück.

    mi_found=True  : MediaInfo-Executable wurde gefunden und gestartet
    mi_found=False : Executable nicht vorhanden oder nicht erreichbar
    """
    warnings: list[str] = []
    mi_exe = getattr(tools, "mediainfo", None)

    # Executable-Prüfung: entweder absoluter Pfad existiert nicht,
    # oder der Eintrag ist leer → nicht gefunden
    exe_str = str(mi_exe) if mi_exe else ""
    if not exe_str or not tool_available(exe_str):
        warnings.append("MediaInfo nicht gefunden")
        return {}, warnings, False

    try:
        result = (run_process or _run_tool)([exe_str, "--Output=JSON", path])
        data = json.loads(result.stdout or "{}")
        if not isinstance(data, dict):
            raise ValueError("MediaInfo JSON hat keinen Objekt-Root")
        return data, warnings, True
    except AnalysisStoppedError:
        raise
    except Exception as e:
        warnings.append(f"MediaInfo-Analyse fehlgeschlagen: {e}")
        warnings.append(traceback.format_exc())
        return {}, warnings, True   # Executable war da, hat aber versagt

def _run_ffprobe_json(path: str, tools: ToolPaths, *, run_process=None) -> tuple[dict, list[str]]:
    warnings: list[str] = []
    try:
        result = (run_process or _run_tool)([
            tools.ffprobe,
            "-v", "error",
            "-show_streams",
            "-show_format",
            "-of", "json",
            path,
        ])
        data = json.loads(result.stdout or "{}")
        if not isinstance(data, dict):
            raise ValueError("ffprobe JSON hat keinen Objekt-Root")
        return data, warnings
    except AnalysisStoppedError:
        raise
    except Exception as e:
        warnings.append(f"ffprobe-Analyse fehlgeschlagen: {e}")
        warnings.append(traceback.format_exc())
        return {}, warnings


def _run_ffprobe_dynamic_hdr_frames(
    path: str,
    tools: ToolPaths,
    *,
    stream_index: int,
    run_process=None,
) -> tuple[dict, list[str]]:
    """Read a short frame window for dynamic HDR side-data.

    ``-show_streams`` does not reliably expose frame-level ST-2094-40
    metadata.  This probe is therefore used only as a fallback when the normal
    MediaInfo/ffprobe stream analysis did not already detect HDR10+.
    """
    warnings: list[str] = []
    try:
        result = (run_process or _run_tool)([
            tools.ffprobe,
            "-v", "error",
            # A numeric selector is the ffprobe global stream index.  Using
            # v:0 here is unsafe for files whose first video stream is cover
            # art/attached_pic and was intentionally filtered by the analyzer.
            "-select_streams", str(stream_index),
            "-read_intervals", "0%+2",
            "-show_frames",
            "-of", "json",
            path,
        ])
        data = json.loads(result.stdout or "{}")
        if not isinstance(data, dict):
            raise ValueError("ffprobe Frame-JSON hat keinen Objekt-Root")
        return data, warnings
    except AnalysisStoppedError:
        raise
    except Exception as e:
        warnings.append(f"ffprobe Dynamic-HDR-Fallback fehlgeschlagen: {e}")
        warnings.append(traceback.format_exc())
        return {}, warnings

def _mi_tracks(mi_json: dict) -> list[dict]:
    if not isinstance(mi_json, dict):
        return []
    media = mi_json.get("media", {}) or {}
    if not isinstance(media, dict):
        return []
    tracks = media.get("track", []) or []
    if isinstance(tracks, dict):
        tracks = [tracks]
    if not isinstance(tracks, list):
        return []
    return [track for track in tracks if isinstance(track, dict)]

def _mi_general_track(mi_json: dict) -> dict:
    for tr in _mi_tracks(mi_json):
        if str(tr.get("@type") or "").lower() == "general":
            return tr
    return {}

def _mi_video_tracks(mi_json: dict) -> list[dict]:
    return [tr for tr in _mi_tracks(mi_json) if str(tr.get("@type") or "").lower() == "video"]

def _mi_audio_tracks(mi_json: dict) -> list[dict]:
    return [tr for tr in _mi_tracks(mi_json) if str(tr.get("@type") or "").lower() == "audio"]

def _mi_text_tracks(mi_json: dict) -> list[dict]:
    return [tr for tr in _mi_tracks(mi_json) if str(tr.get("@type") or "").lower() == "text"]

def _fp_streams_by_type(fp_json: dict, stream_type: str) -> list[dict]:
    if not isinstance(fp_json, dict):
        return []
    streams = fp_json.get("streams", []) or []
    if isinstance(streams, dict):
        streams = [streams]
    if not isinstance(streams, list):
        return []
    streams = [stream for stream in streams if isinstance(stream, dict)]
    stream_type_key = str(stream_type or "").lower()
    result = [s for s in streams if str(s.get("codec_type") or "").lower() == stream_type_key]
    if stream_type == "video":
        # ffprobe exposes cover art as a video stream with attached_pic=1.
        # The conversion pipeline operates on the first *real* video stream
        # (0:v:0), so attached pictures must never become MediaInfo.primary_video.
        result = [
            s for s in result
            if not _safe_bool(
                (s.get("disposition") if isinstance(s.get("disposition"), dict) else {}).get(
                    "attached_pic", 0
                )
            )
        ]
    return result

def _mi_bitrate(track: dict) -> int | None:
    for key in ("BitRate", "BitRate_Nominal", "OverallBitRate"):
        value = track.get(key)
        if value is None:
            continue
        try:
            return int(float(str(value).replace(" ", "")))
        except (TypeError, ValueError, OverflowError):
            continue
    return None

def _mi_forced(track: dict) -> bool:
    """Liest das Forced-Flag aus einem MediaInfo-Track-Dict."""
    return str(track.get("Forced") or "").strip().lower() in {"yes", "true", "1"}


def _mi_default(track: dict) -> bool:
    """Liest das Default-Flag aus einem MediaInfo-Track-Dict."""
    return str(track.get("Default") or "").strip().lower() in {"yes", "true", "1"}

def _mi_stream_index(track: dict, fallback: int) -> int:
    """Liest MediaInfos StreamOrder nur als MediaInfo-eigenen Ordnungswert.

    WICHTIG: Dieser Wert ist *kein* garantierter ffmpeg/ffprobe-Streamindex.
    Bei Blu-ray/Playlist-Quellen kann MediaInfo z. B. Audio-StreamOrder 0/1
    melden, während ffprobe dieselben Spuren als globale Indizes 2/3 führt.
    Für ``-map 0:<index>`` darf ausschließlich ein ffprobe-Index verwendet
    werden.
    """
    return _safe_int(track.get("StreamOrder"), fallback)


def _ffmpeg_stream_index(fp_stream: dict, fallback_ordinal: int) -> int:
    """Return a trustworthy ffprobe global stream index or a fail-closed sentinel.

    Negative values are intentionally impossible ffmpeg stream indices.  They
    keep tracks distinct for UI/rules while ensuring a missing ffprobe result
    can never silently map a different audio/subtitle stream.
    """
    if fp_stream:
        raw_index = fp_stream.get("index")
        index: int | None = None
        if isinstance(raw_index, int) and not isinstance(raw_index, bool):
            index = raw_index
        elif isinstance(raw_index, float) and raw_index.is_integer():
            index = int(raw_index)
        elif isinstance(raw_index, str):
            text = raw_index.strip()
            if re.fullmatch(r"\+?[0-9]+", text):
                try:
                    index = int(text)
                except ValueError:
                    pass
        if index is not None and index >= 0:
            return index
    return -(int(fallback_ordinal) + 1)


def _warn_untrusted_stream_index(
    warnings: list[str] | None,
    *,
    stream_type: str,
    ordinal: int,
) -> None:
    if warnings is None:
        return
    message = (
        "[Stream-ID] ffprobe liefert keinen verlässlichen globalen Streamindex für "
        f"{stream_type}-Spur {ordinal + 1}; MediaInfo StreamOrder wird bewusst nicht als "
        "ffmpeg-Index interpretiert. Verarbeitung mit -map muss fail-closed abbrechen."
    )
    if message not in warnings:
        warnings.append(message)

def _mi_codec_audio(track: dict) -> str:
    """Normalisiert MediaInfo Audio-Format auf ffprobe-konforme Kleinschreibung."""
    fmt = str(track.get("Format") or "").strip()
    mapping = {
        "E-AC-3": "eac3", "AC-3": "ac3", "AAC": "aac", "DTS": "dts",
        "TrueHD": "truehd", "Opus": "opus", "Vorbis": "vorbis",
        "FLAC": "flac", "MP3": "mp3", "PCM": "pcm",
    }
    return mapping.get(fmt, fmt.lower())
