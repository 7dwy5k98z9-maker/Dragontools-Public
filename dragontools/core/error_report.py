from __future__ import annotations

import json
import re
import traceback
from dataclasses import asdict, is_dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from .logger import resolve_log_month_dir


_MAX_TEXT_CHARS = 20_000
_MAX_LINES_PER_GROUP = 40


def write_conversion_error_report(
    *,
    ctx: Any,
    reason: str,
    tool_output: str = "",
    log_file: str | Path | None = None,
    traceback_text: str = "",
) -> str:
    """Schreibt einen Diagnosebericht für eine fehlgeschlagene Datei.

    Der Bericht ist absichtlich Plain-Text, damit er auch ohne DragonTools
    lesbar bleibt und für Support/Fehlersuche einfach weitergegeben werden kann.
    """
    report_dir = resolve_log_month_dir(log_file) / "ErrorReports"
    report_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now()
    input_path = str(getattr(ctx, "input_path", "") or "")
    stem = Path(input_path).stem or "unbekannte_datei"
    report_path = report_dir / (
        f"{timestamp.strftime('%Y%m%d_%H%M%S')}_"
        f"{_safe_filename(stem)[:80]}_error.txt"
    )

    text = "\n".join(
        [
            "DragonTools Fehlerbericht",
            "=" * 80,
            f"Zeitpunkt: {timestamp.strftime('%d.%m.%Y %H:%M:%S')}",
            f"Datei: {_value(input_path)}",
            f"Fehlergrund: {_value(reason)}",
            "",
            _section("Workflow", _workflow_lines(ctx)),
            _section("Pipeline-Diagnose", _pipeline_diagnostic_lines(ctx)),
            _section("Quelle", _source_lines(ctx)),
            _section("Ausgabe / Pfade", _path_lines(ctx)),
            _section("Encoder / Profil", _encoder_lines(ctx)),
            _section("Per-Datei-Override", _override_lines(ctx)),
            _section("Output-Validierung", _verify_lines(ctx)),
            _section("Letzte Tool-Ausgabe", _text_lines(tool_output)),
            _section("Interner Traceback", _text_lines(traceback_text)),
        ]
    ).rstrip() + "\n"

    report_path.write_text(text, encoding="utf-8")
    return str(report_path)


def build_error_report_preview(path: str | None, *, max_chars: int = 1000) -> str:
    """Liest einen kurzen Vorschautext für GUI/Tests, ohne bei Fehlern zu werfen."""
    if not path:
        return ""
    try:
        p = Path(path)
        if not p.exists():
            return ""
        text = p.read_text(encoding="utf-8", errors="replace")
        return text[:max_chars]
    except Exception:
        return ""


def _section(title: str, lines: list[str]) -> str:
    cleaned = [line for line in lines if line is not None]
    if not cleaned:
        cleaned = ["-"]
    return "\n".join([title, "-" * len(title), *cleaned, ""])


def _workflow_lines(ctx: Any) -> list[str]:
    return [
        f"Pipeline: {_value(getattr(ctx, 'pipeline', ''))}",
        f"Container: {_value(getattr(ctx, 'container', ''))}",
        f"Strategie: {_value(getattr(ctx, 'strategy_name', ''))}",
        f"Original ersetzen: {_yes_no(getattr(ctx, 'replace_original', False))}",
        f"Strip-only: {_yes_no(getattr(ctx, 'strip_only', None))}",
    ]


def _pipeline_diagnostic_lines(ctx: Any) -> list[str]:
    reason = str(getattr(ctx, "pipeline_failure_reason", "") or "").strip()
    stage = str(getattr(ctx, "pipeline_failure_stage", "") or "").strip()
    tool = str(getattr(ctx, "pipeline_failure_tool", "") or "").strip()
    command = str(getattr(ctx, "pipeline_failure_command", "") or "").strip()
    if not any((reason, stage, tool, command)):
        return ["Keine zusätzliche Pipeline-Diagnose verfügbar."]
    return [
        f"Fehlerstufe: {_value(stage)}",
        f"Ursache: {_value(reason)}",
        f"Tool: {_value(tool)}",
        f"Kommando: {_value(command)}",
    ]


def _source_lines(ctx: Any) -> list[str]:
    analysis = getattr(ctx, "analysis", None)
    primary = getattr(analysis, "primary_video", None) if analysis is not None else None
    lines = [
        f"Analysedatei: {_value(getattr(analysis, 'path', None) or getattr(ctx, 'input_path', ''))}",
        f"Analysetools: {_value(getattr(analysis, 'analysis_source', ''))}",
        f"Quellgröße: {_format_size(getattr(ctx, 'size_before', 0))}",
        f"Quell-Dauer: {_format_duration_ms(getattr(ctx, 'duration_ms', None))}",
        f"Video: {_stream_summary(primary)}",
        f"HDR: {_hdr_summary(analysis, primary)}",
        f"Audio-Spuren: {len(getattr(analysis, 'audio_streams', []) or [])}",
        f"Untertitel-Spuren: {len(getattr(analysis, 'subtitle_streams', []) or [])}",
    ]
    warnings = list(getattr(analysis, "analysis_warnings", []) or []) if analysis is not None else []
    if warnings:
        lines.append("Analyse-Warnungen:")
        lines.extend(f"  - {_value(warning)}" for warning in warnings[:_MAX_LINES_PER_GROUP])
    return lines


def _path_lines(ctx: Any) -> list[str]:
    sidecars = list(getattr(ctx, "sidecar_paths", []) or [])
    lines = [
        f"Arbeitsordner: {_value(getattr(ctx, 'base_dir', None))}",
        f"Geplante Ausgabe: {_value(getattr(ctx, 'output_path', None))}",
        f"Finale Ausgabe: {_value(getattr(ctx, 'final_output_path', None))}",
        f"Sidecars: {len(sidecars)}",
    ]
    lines.extend(f"  - {_value(path)}" for path in sidecars[:_MAX_LINES_PER_GROUP])
    return lines


def _encoder_lines(ctx: Any) -> list[str]:
    options = getattr(ctx, "effective_encoder_options", None) or {}
    return [
        f"Codec: {_value(getattr(ctx, 'effective_codec', ''))}",
        f"Qualität/CQ/CRF: {_value(getattr(ctx, 'effective_crf', None))}",
        f"Preset: {_value(getattr(ctx, 'effective_preset', ''))}",
        f"Scale-Modus: {_value(getattr(ctx, 'effective_scale_mode', ''))}",
        f"Profil: {_value(getattr(ctx, 'encoder_profile_label', ''))}",
        f"Encoder-Optionen: {_json(options)}",
    ]


def _override_lines(ctx: Any) -> list[str]:
    override = getattr(ctx, "file_override", None)
    if not override:
        return ["Kein Per-Datei-Override aktiv."]
    return _json(override).splitlines()


def _verify_lines(ctx: Any) -> list[str]:
    result = getattr(ctx, "verify_result", None)
    if result is None:
        return ["Validierung wurde noch nicht erreicht."]
    fields = [
        "exists",
        "size_ok",
        "container_ok",
        "probe_ok",
        "video_ok",
        "audio_ok",
        "duration_ok",
        "format_name",
        "duration_s",
        "video_stream_count",
        "audio_stream_count",
    ]
    lines = [f"{name}: {_value(getattr(result, name, None))}" for name in fields]
    messages = list(getattr(result, "messages", []) or [])
    if messages:
        lines.append("Meldungen:")
        lines.extend(f"  - {_value(message)}" for message in messages[:_MAX_LINES_PER_GROUP])
    if bool(getattr(ctx, "duration_repair_attempted", False)):
        lines.append("Automatische Laufzeitreparatur:")
        method = getattr(ctx, "duration_repair_method", "")
        if method:
            lines.append(f"  - Methode: {_value(method)}")
        lines.append(f"  - Dauer nach FFmpeg: {_format_duration_s(getattr(ctx, 'duration_after_ffmpeg_s', None))}")
        lines.append(f"  - Dauer nach Remux: {_format_duration_s(getattr(ctx, 'duration_after_remux_s', None))}")
        lines.append(
            f"  - Dauer nach Timestamp-Fix: {_format_duration_s(getattr(ctx, 'duration_after_timestamp_fix_s', None))}"
        )
        reason = getattr(ctx, "duration_repair_reason", "")
        if reason:
            lines.append(f"  - Reparaturgrund: {_value(reason)}")
        cmd = (
            getattr(ctx, "duration_repair_command", None)
            or getattr(ctx, "duration_repair_ffmpeg_cmd", None)
        )
        if cmd:
            executable = Path(str(cmd[0])).name.lower() if cmd else ""
            if "mp4box" in executable:
                command_label = "MP4Box-Befehl"
            elif "ffmpeg" in executable:
                command_label = "FFmpeg-Befehl"
            elif "mkvmerge" in executable:
                command_label = "MKVToolNix-Befehl"
            else:
                command_label = "Reparaturbefehl"
            lines.append(f"  - {command_label}: {_value(' '.join(str(part) for part in cmd))}")
        timing = list(getattr(ctx, "duration_repair_timing_summary", []) or [])
        if timing:
            lines.append("  - Timing-Pr\u00fcfung:")
            lines.extend(f"    - {_value(line)}" for line in timing[:_MAX_LINES_PER_GROUP])
        archive_path = getattr(ctx, "duration_repair_archive_path", None)
        if archive_path:
            lines.append(f"  - Archiviert: {_value(archive_path)}")
    return lines


def _text_lines(text: str) -> list[str]:
    text = str(text or "").strip()
    if not text:
        return ["-"]
    trimmed = text[-_MAX_TEXT_CHARS:]
    lines = trimmed.splitlines()
    if len(lines) > _MAX_LINES_PER_GROUP:
        lines = lines[-_MAX_LINES_PER_GROUP:]
    return lines


def _stream_summary(stream: Any) -> str:
    if stream is None:
        return "-"
    codec = getattr(stream, "codec", "")
    width = getattr(stream, "width", None)
    height = getattr(stream, "height", None)
    bit_depth = getattr(stream, "bit_depth", None)
    pix_fmt = getattr(stream, "pix_fmt", "")
    parts = [_value(codec)]
    if width and height:
        parts.append(f"{width}x{height}")
    if bit_depth:
        parts.append(f"{bit_depth} bit")
    if pix_fmt:
        parts.append(str(pix_fmt))
    return ", ".join(part for part in parts if part and part != "-")


def _hdr_summary(analysis: Any, primary: Any) -> str:
    if analysis is None:
        return "-"
    parts = []
    if bool(getattr(analysis, "has_dv", False)) or bool(getattr(analysis, "dolby_vision", False)):
        profile = getattr(analysis, "dolby_vision_profile", None) or getattr(analysis, "dv_profile", None)
        parts.append(f"DV Profil {profile or '?'}")
    if bool(getattr(analysis, "has_hdrplus", False)) or bool(getattr(analysis, "has_hdr10plus", False)):
        parts.append("HDR10+")
    if bool(getattr(analysis, "is_hdr", False)):
        parts.append("HDR")
    if primary is not None:
        for attr in ("hdr_format", "color_space", "color_transfer", "color_primaries"):
            val = getattr(primary, attr, None)
            if val:
                parts.append(f"{attr}={val}")
    return ", ".join(parts) if parts else "SDR/kein HDR erkannt"


def _encoder_option(ctx: Any, key: str) -> Any:
    options = getattr(ctx, "effective_encoder_options", None) or {}
    if isinstance(options, dict):
        return options.get(key)
    return None


def _json(value: Any) -> str:
    try:
        data = _plain(value)
        return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True)
    except Exception:
        return _value(value)


def _plain(value: Any) -> Any:
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, dict):
        return {str(k): _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_plain(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _format_size(value: Any) -> str:
    try:
        amount = float(value or 0)
    except Exception:
        return _value(value)
    units = ["B", "KB", "MB", "GB", "TB"]
    unit = units[0]
    for unit in units:
        if abs(amount) < 1024 or unit == units[-1]:
            break
        amount /= 1024.0
    if unit == "B":
        return f"{int(amount)} {unit}"
    return f"{amount:.2f} {unit}"


def _format_duration_s(value: Any) -> str:
    try:
        if value is None:
            return "-"
        return f"{float(value):.1f}s"
    except (TypeError, ValueError):
        return _value(value)


def _format_duration_ms(value: Any) -> str:
    try:
        if value is None:
            return "-"
        seconds = float(value) / 1000.0
    except Exception:
        return _value(value)
    return f"{seconds:.1f}s"


def _yes_no(value: Any) -> str:
    if value is None:
        return "-"
    return "Ja" if bool(value) else "Nein"


def _value(value: Any) -> str:
    if value is None or value == "":
        return "-"
    return str(value)


def _safe_filename(value: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._ -]+", "_", value.strip())
    safe = re.sub(r"\s+", " ", safe).strip(" .")
    return safe or "unbekannte_datei"


def current_traceback_text() -> str:
    return traceback.format_exc()
