# -*- coding: utf-8 -*-
"""
dragontools/subtitle/converter.py
SRT ↔ ASS ↔ TXT Konvertierung.
"""
from __future__ import annotations
import re
from pathlib import Path

_SRT_BLOCK = re.compile(
    r"(\d+)\r?\n"
    r"(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\r?\n"
    r"([\s\S]*?)(?=\r?\n\r?\n|\Z)",
    re.MULTILINE
)
_ASS_DIALOGUE = re.compile(
    r"^Dialogue:\s*[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,[^,]*,(.*)$",
    re.MULTILINE,
)
_TXT_TIMECODE_LINE = re.compile(
    r"^\s*"
    r"(?P<start>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
    r"\s*-->\s*"
    r"(?P<end>\d{1,2}:\d{2}:\d{2}[,.]\d{1,3})"
    r"(?:\s+.*)?$"
)
_TAG_RE = re.compile(r"<[^>]+>")
_ASS_TAG_RE = re.compile(r"\{[^}]*\}")


def _read_text(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8", errors="replace").replace(
        "\r\n", "\n"
    ).replace("\r", "\n").lstrip("\ufeff")


def _normalize_srt_timestamp(value: str) -> str:
    m = re.match(r"^(\d{1,2}):(\d{2}):(\d{2})([,.])(\d{1,3})$", value.strip())
    if not m:
        raise ValueError(f"Ungültiger Zeitstempel: {value!r}")
    h, minute, second, _sep, fraction = m.groups()
    ms = int(fraction.ljust(3, "0")[:3])
    return f"{int(h):02d}:{int(minute):02d}:{int(second):02d},{ms:03d}"


def _srt_ts_to_ass(t: str) -> str:
    h, m, s_ms = t.split(":")
    s, ms = s_ms.split(",")
    cs = int(ms) // 10
    return f"{int(h)}:{int(m):02d}:{int(s):02d}.{cs:02d}"


def _ass_ts_to_srt(t: str) -> str:
    m = re.match(r"^(\d{1,2}):(\d{2}):(\d{2})[.](\d{1,3})$", t.strip())
    if not m:
        raise ValueError(f"Ungültiger ASS-Zeitstempel: {t!r}")
    h, minute, second, fraction = m.groups()
    ms = int(fraction) * 10 if len(fraction) == 2 else int(fraction.ljust(3, "0")[:3])
    return f"{int(h):02d}:{int(minute):02d}:{int(second):02d},{ms:03d}"


def _ass_header(style: str | None = None) -> str:
    default_style = (
        "Style: Default,Arial,22,&H00FFFFFF,&H000000FF,&H00000000,&H80000000,"
        "0,0,0,0,100,100,0,0,1,2,2,2,10,10,10,1"
    )
    return (
        "[Script Info]\nScriptType: v4.00+\nCollisions: Normal\n"
        "PlayResX: 1920\nPlayResY: 1080\n\n"
        "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, "
        "SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, "
        "StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, "
        "Shadow, Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"{style or default_style}\n\n"
        "[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    )


def _srt_text_to_ass(text: str, style: str | None = None) -> str:
    events = []
    for m in _SRT_BLOCK.finditer(text):
        start = _srt_ts_to_ass(m.group(2))
        end = _srt_ts_to_ass(m.group(3))
        content = m.group(4).strip().replace("\n", "\\N")
        content = _TAG_RE.sub("", content)
        events.append(f"Dialogue: 0,{start},{end},Default,,0,0,0,,{content}")
    return _ass_header(style) + "\n".join(events)


def _parse_timestamped_txt(text: str) -> list[tuple[str, str, str]]:
    cues: list[tuple[str, str, str]] = []
    current: tuple[str, str, list[str]] | None = None

    def flush() -> None:
        nonlocal current
        if current is None:
            return
        start, end, content_lines = current
        while content_lines and not content_lines[0].strip():
            content_lines.pop(0)
        while content_lines and not content_lines[-1].strip():
            content_lines.pop()
        content = "\n".join(content_lines).strip()
        if content:
            cues.append((start, end, content))
        current = None

    for line in text.split("\n"):
        match = _TXT_TIMECODE_LINE.match(line)
        if match:
            flush()
            current = (
                _normalize_srt_timestamp(match.group("start")),
                _normalize_srt_timestamp(match.group("end")),
                [],
            )
            continue
        if current is not None:
            current[2].append(line)
    flush()
    return cues


def srt_to_txt(srt_path: str | Path, output_path: str | Path | None = None) -> str:
    text = _read_text(srt_path)
    lines = []
    for m in _SRT_BLOCK.finditer(text):
        content = m.group(4).strip()
        content = _TAG_RE.sub("", content)
        if content:
            lines.append(f"{m.group(2)} --> {m.group(3)}\n{content}")
    result = "\n\n".join(lines)
    if output_path:
        Path(output_path).write_text(result, encoding="utf-8")
    return result

def srt_to_ass(srt_path: str | Path, output_path: str | Path | None = None,
               style: str | None = None) -> str:
    result = _srt_text_to_ass(_read_text(srt_path), style)
    if output_path:
        Path(output_path).write_text(result, encoding="utf-8")
    return result


def txt_to_srt(txt_path: str | Path, output_path: str | Path | None = None) -> str:
    cues = _parse_timestamped_txt(_read_text(txt_path))
    if not cues:
        raise ValueError(
            "TXT enthält keine erkennbaren Zeitstempel im Format "
            "00:00:00,000 --> 00:00:00,000."
        )
    blocks = [
        f"{idx}\n{start} --> {end}\n{content}"
        for idx, (start, end, content) in enumerate(cues, start=1)
    ]
    result = "\n\n".join(blocks)
    if output_path:
        Path(output_path).write_text(result, encoding="utf-8")
    return result


def txt_to_ass(txt_path: str | Path, output_path: str | Path | None = None,
               style: str | None = None) -> str:
    result = _srt_text_to_ass(txt_to_srt(txt_path), style)
    if output_path:
        Path(output_path).write_text(result, encoding="utf-8")
    return result


def ass_to_txt(ass_path: str | Path, output_path: str | Path | None = None) -> str:
    text = _read_text(ass_path)
    lines = []
    for raw_line in text.split("\n"):
        if not raw_line.startswith("Dialogue:"):
            continue
        parts = raw_line[len("Dialogue:"):].strip().split(",", 9)
        if len(parts) < 10:
            continue
        try:
            start = _ass_ts_to_srt(parts[1])
            end = _ass_ts_to_srt(parts[2])
        except ValueError:
            continue
        content = parts[9].replace("\\N", "\n").replace("\\n", "\n")
        content = _ASS_TAG_RE.sub("", content)
        content = _TAG_RE.sub("", content).strip()
        if content:
            lines.append(f"{start} --> {end}\n{content}")
    result = "\n\n".join(lines)
    if output_path:
        Path(output_path).write_text(result, encoding="utf-8")
    return result


def subtitle_to_txt(subtitle_path: str | Path, output_path: str | Path | None = None) -> str:
    path = Path(subtitle_path)
    suffix = path.suffix.lower()
    if suffix == ".srt":
        return srt_to_txt(path, output_path)
    if suffix in {".ass", ".ssa"}:
        return ass_to_txt(path, output_path)
    if suffix == ".txt":
        result = path.read_text(encoding="utf-8", errors="replace").strip()
        if output_path:
            Path(output_path).write_text(result, encoding="utf-8")
        return result
    raise ValueError(f"TXT-Export unterstuetzt dieses Format nicht: {suffix or 'ohne Endung'}")
