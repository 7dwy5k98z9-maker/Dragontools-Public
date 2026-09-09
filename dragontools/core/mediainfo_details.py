# -*- coding: utf-8 -*-
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .media_metadata import _parse_mediainfo_duration_s
from .models import MediaInfo
from .paths import get_tool_paths
from .process_runner import run_analysis_tool


MISSING = "—"


@dataclass(slots=True)
class MediaInfoDisplayDetails:
    source: str = "MediaInfo.exe"
    overview_rows: list[tuple[str, str]] = field(default_factory=list)
    video_rows: list[tuple[str, str]] = field(default_factory=list)
    audio_rows: list[dict[str, str]] = field(default_factory=list)
    subtitle_rows: list[dict[str, str]] = field(default_factory=list)
    raw_text: str = ""
    warning: str | None = None


def load_mediainfo_json(file_path: str) -> tuple[dict[str, Any], str | None]:
    """Lädt die vollständige MediaInfo-JSON-Ausgabe für die Detailansicht."""
    try:
        exe = get_tool_paths().mediainfo
        result = run_analysis_tool([exe, "--Output=JSON", file_path], timeout=60)
        return json.loads(result.stdout or "{}"), None
    except Exception as exc:
        return {}, str(exc)


def build_mediainfo_display_details(
    file_path: str,
    *,
    media_info: MediaInfo | None = None,
    payload: dict[str, Any] | None = None,
) -> MediaInfoDisplayDetails:
    warning: str | None = None
    if payload is None:
        payload, warning = load_mediainfo_json(file_path)

    tracks = _tracks(payload)
    general = _first_track(tracks, "general")
    videos = _tracks_of_type(tracks, "video")
    audios = _tracks_of_type(tracks, "audio")
    subtitles = _tracks_of_type(tracks, "text")
    menus = _tracks_of_type(tracks, "menu")

    if not payload:
        return _fallback_details(file_path, media_info, warning)

    video_bitrate = _first_number(videos[0] if videos else {}, "BitRate", "BitRate_Nominal")
    audio_bitrate_sum = sum(
        value or 0
        for value in (_first_number(track, "BitRate", "BitRate_Nominal") for track in audios)
    )
    overall_bitrate = _first_number(general, "OverallBitRate", "BitRate")
    estimated_video_bitrate = None
    if not video_bitrate and overall_bitrate and audio_bitrate_sum:
        estimated_video_bitrate = max(0, overall_bitrate - audio_bitrate_sum)

    duration_s = _duration(general.get("Duration"))
    file_size = _first_number(general, "FileSize")
    if not file_size:
        try:
            file_size = Path(file_path).stat().st_size
        except OSError:
            file_size = None

    overview_rows = [
        ("Container", _join_values(general.get("Format"), general.get("Format_Profile"))),
        ("Dateigröße", _format_size(file_size)),
        ("Dauer", _format_duration(duration_s)),
        ("Gesamtbitrate", _format_bitrate(overall_bitrate)),
        (
            "Videobitrate",
            _format_bitrate(video_bitrate)
            if video_bitrate
            else _format_bitrate(estimated_video_bitrate, suffix=" (geschätzt)"),
        ),
        ("Video", str(len(videos)) if videos else MISSING),
        ("Audio", str(len(audios)) if audios else "0"),
        ("Untertitel", str(len(subtitles)) if subtitles else "0"),
        ("Kapitel/Menüs", str(len(menus)) if menus else "0"),
        ("Analysetool", "MediaInfo.exe"),
    ]

    video_rows = _build_video_rows(videos[0] if videos else {}, media_info=media_info)
    audio_rows = [_build_audio_row(track, idx) for idx, track in enumerate(audios, start=1)]
    subtitle_rows = [_build_subtitle_row(track, idx) for idx, track in enumerate(subtitles, start=1)]

    raw_text = json.dumps(payload, ensure_ascii=False, indent=2)
    return MediaInfoDisplayDetails(
        source="MediaInfo.exe",
        overview_rows=overview_rows,
        video_rows=video_rows,
        audio_rows=audio_rows,
        subtitle_rows=subtitle_rows,
        raw_text=raw_text,
        warning=warning,
    )


def _fallback_details(
    file_path: str,
    media_info: MediaInfo | None,
    warning: str | None,
) -> MediaInfoDisplayDetails:
    if media_info is None:
        return MediaInfoDisplayDetails(
            source="Fallback",
            overview_rows=[
                ("Datei", Path(file_path).name),
                ("Analysetool", "MediaInfo nicht verfügbar"),
            ],
            raw_text="",
            warning=warning or "MediaInfo konnte keine Daten liefern.",
        )

    video = media_info.primary_video
    overview_rows = [
        ("Container", Path(file_path).suffix.lstrip(".").upper() or MISSING),
        ("Dateigröße", _format_size(media_info.size_bytes)),
        ("Dauer", _format_duration(media_info.duration_s)),
        ("Gesamtbitrate", MISSING),
        ("Video", str(len(media_info.video_streams))),
        ("Audio", str(len(media_info.audio_streams))),
        ("Untertitel", str(len(media_info.subtitle_streams))),
        ("Analysetool", media_info.analysis_source),
    ]
    video_rows = []
    if video:
        video_rows = [
            ("Codec", _value(video.codec)),
            ("Auflösung", f"{video.width}×{video.height}" if video.width and video.height else MISSING),
            ("Framerate", _value(video.frame_rate)),
            ("Framerate-Modus", _value(video.frame_rate_mode)),
            ("Frames", _format_int(video.frame_count)),
            ("Bit-Tiefe", f"{video.bit_depth} Bit" if video.bit_depth else MISSING),
            ("Pixelformat", _value(video.pix_fmt)),
            ("HDR", _value(video.hdr_format or ("HDR" if media_info.is_hdr else "SDR"))),
        ]

    return MediaInfoDisplayDetails(
        source=media_info.analysis_source,
        overview_rows=overview_rows,
        video_rows=video_rows,
        raw_text="",
        warning=warning,
    )


def _build_video_rows(track: dict[str, Any], *, media_info: MediaInfo | None) -> list[tuple[str, str]]:
    if not track:
        return []
    width = _first_number(track, "Width")
    height = _first_number(track, "Height")
    hdr_format = _join_values(
        track.get("HDR_Format"),
        track.get("HDR_Format_Profile"),
        track.get("HDR_Format_Compatibility"),
    )
    if hdr_format == MISSING and media_info:
        hdr_format = media_info.primary_video.hdr_format if media_info.primary_video else None

    return [
        ("Stream", _stream_label(track, 1)),
        ("Codec", _join_values(track.get("Format"), track.get("Format_Profile"), track.get("CodecID"))),
        ("Auflösung", f"{_format_int(width)}×{_format_int(height)}" if width and height else MISSING),
        ("Framerate", _fps_label(track.get("FrameRate"), track.get("FrameRate_Num"), track.get("FrameRate_Den"))),
        ("Framerate-Modus", _value(track.get("FrameRate_Mode"))),
        ("Dauer", _format_duration(_duration(track.get("Duration")))),
        ("Frames", _format_int(_first_number(track, "FrameCount"))),
        ("Bitrate", _format_bitrate(_first_number(track, "BitRate", "BitRate_Nominal"))),
        ("Stream-Größe", _format_size(_first_number(track, "StreamSize"))),
        ("Bit-Tiefe", _bit_depth_label(track)),
        ("Chroma", _value(track.get("ChromaSubsampling"))),
        ("Farbraum", _value(track.get("colour_space") or track.get("ColorSpace"))),
        ("Transfer", _value(track.get("transfer_characteristics") or track.get("TransferCharacteristics"))),
        ("Primärfarben", _value(track.get("colour_primaries") or track.get("ColorPrimaries"))),
        ("Matrix", _value(track.get("matrix_coefficients") or track.get("MatrixCoefficients"))),
        ("Farbbereich", _value(track.get("colour_range") or track.get("ColorRange"))),
        ("HDR-Format", _value(hdr_format)),
        ("Mastering Display", _value(track.get("MasteringDisplay_ColorPrimaries"))),
        ("MaxCLL / MaxFALL", _join_values(track.get("MaxCLL"), track.get("MaxFALL"), separator=" / ")),
        ("Bits/(Pixel*Frame)", _value(track.get("Bits-(Pixel*Frame)") or track.get("Bits__Pixel_Frame_"))),
        ("Encoder", _value(track.get("Encoded_Library") or track.get("WritingLibrary"))),
    ]


def _build_audio_row(track: dict[str, Any], fallback_index: int) -> dict[str, str]:
    return {
        "Spur": _stream_label(track, fallback_index),
        "Sprache": _language_label(track),
        "Codec": _join_values(track.get("Format"), track.get("Format_Profile")),
        "Kanäle": _channels_label(track),
        "Bitrate": _format_bitrate(_first_number(track, "BitRate", "BitRate_Nominal")),
        "Sampling": _sampling_label(track),
        "Dauer": _format_duration(_duration(track.get("Duration"))),
        "Titel": _value(track.get("Title")),
        "Flags": _flags_label(track),
    }


def _build_subtitle_row(track: dict[str, Any], fallback_index: int) -> dict[str, str]:
    return {
        "Spur": _stream_label(track, fallback_index),
        "Sprache": _language_label(track),
        "Format": _join_values(track.get("Format"), track.get("CodecID")),
        "Titel": _value(track.get("Title")),
        "Flags": _flags_label(track),
    }


def _tracks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    media = payload.get("media", {}) if isinstance(payload, dict) else {}
    tracks = media.get("track", []) if isinstance(media, dict) else []
    return [track for track in tracks if isinstance(track, dict)]


def _tracks_of_type(tracks: list[dict[str, Any]], kind: str) -> list[dict[str, Any]]:
    return [track for track in tracks if str(track.get("@type") or "").lower() == kind]


def _first_track(tracks: list[dict[str, Any]], kind: str) -> dict[str, Any]:
    return next(iter(_tracks_of_type(tracks, kind)), {})


def _first_number(track: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = track.get(key)
        if value in (None, "", "N/A"):
            continue
        try:
            return int(float(str(value).strip().replace(" ", "").replace(",", ".")))
        except ValueError:
            continue
    return None


def _duration(value: Any) -> float | None:
    return _parse_mediainfo_duration_s(value)


def _value(value: Any, fallback: str = MISSING) -> str:
    if value is None:
        return fallback
    text = str(value).strip()
    return text if text else fallback


def _join_values(*values: Any, separator: str = " / ") -> str:
    parts = [_value(value, "") for value in values]
    parts = [part for part in parts if part]
    return separator.join(parts) if parts else MISSING


def _format_int(value: Any) -> str:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return MISSING
    return f"{number:,}".replace(",", ".")


def _format_size(bytes_value: Any) -> str:
    try:
        size = float(bytes_value)
    except (TypeError, ValueError):
        return MISSING
    if size <= 0:
        return MISSING
    units = ("Byte", "KB", "MB", "GB", "TB")
    unit_index = 0
    while size >= 1024 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1
    if unit_index == 0:
        return f"{int(size)} {units[unit_index]}"
    return f"{size:.2f} {units[unit_index]}"


def _format_bitrate(value: Any, *, suffix: str = "") -> str:
    try:
        bitrate = float(value)
    except (TypeError, ValueError):
        return MISSING
    if bitrate <= 0:
        return MISSING
    if bitrate >= 1_000_000:
        return f"{bitrate / 1_000_000:.2f} Mb/s{suffix}"
    if bitrate >= 1000:
        return f"{bitrate / 1000:.0f} kb/s{suffix}"
    return f"{int(bitrate)} b/s{suffix}"


def _format_duration(seconds_value: Any) -> str:
    try:
        seconds = float(seconds_value)
    except (TypeError, ValueError):
        return MISSING
    if seconds <= 0:
        return MISSING
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    seconds_part = seconds - hours * 3600 - minutes * 60
    if hours:
        return f"{hours:02d}:{minutes:02d}:{seconds_part:04.1f} ({seconds:.1f}s)"
    return f"{minutes:02d}:{seconds_part:04.1f} ({seconds:.1f}s)"


def _fps_label(frame_rate: Any, numerator: Any = None, denominator: Any = None) -> str:
    if numerator and denominator:
        try:
            num = int(numerator)
            den = int(denominator)
            if den > 0:
                return f"{num}/{den} ({num / den:.3f} fps)"
        except (TypeError, ValueError):
            pass
    text = _value(frame_rate)
    if text == MISSING:
        return MISSING
    try:
        value = float(text.replace(",", "."))
        return f"{value:.3f} fps"
    except ValueError:
        return text


def _bit_depth_label(track: dict[str, Any]) -> str:
    depth = _first_number(track, "BitDepth", "BitDepth/String")
    return f"{depth} Bit" if depth else MISSING


def _channels_label(track: dict[str, Any]) -> str:
    channels = _first_number(track, "Channels")
    layout = _value(track.get("ChannelLayout") or track.get("ChannelLayout_Original"), "")
    if not channels:
        return layout or MISSING
    if channels >= 8:
        base = "7.1"
    elif channels >= 6:
        base = "5.1"
    elif channels == 2:
        base = "Stereo"
    elif channels == 1:
        base = "Mono"
    else:
        base = str(channels)
    return f"{base} ({layout})" if layout else base


def _sampling_label(track: dict[str, Any]) -> str:
    rate = _first_number(track, "SamplingRate")
    if not rate:
        return MISSING
    return f"{rate / 1000:.1f} kHz"


def _language_label(track: dict[str, Any]) -> str:
    language = (
        track.get("Language_String")
        or track.get("Language")
        or track.get("Language_String3")
        or track.get("Language/String")
    )
    return _value(language, "Unbekannt")


def _flags_label(track: dict[str, Any]) -> str:
    flags: list[str] = []
    default = str(track.get("Default") or "").strip().lower()
    forced = str(track.get("Forced") or "").strip().lower()
    if default == "yes":
        flags.append("Default")
    if forced == "yes":
        flags.append("Forced")
    return ", ".join(flags) if flags else MISSING


def _stream_label(track: dict[str, Any], fallback_index: int) -> str:
    for key in ("StreamOrder", "ID", "UniqueID"):
        value = track.get(key)
        if value not in (None, "", "N/A"):
            return f"#{value}"
    return f"#{fallback_index}"
