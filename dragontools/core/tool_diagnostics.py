from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

from .process_runner import subprocess_no_window_kwargs


TOOL_VERSION_ARGS: dict[str, list[str]] = {
    "ffmpeg": ["-hide_banner", "-version"],
    "ffprobe": ["-hide_banner", "-version"],
    "mkvmerge": ["--version"],
    "mkvextract": ["--version"],
    "makemkvcon": ["--version"],
    "mediainfo": ["--Version"],
    "dovi_tool": ["--version"],
    "hdr10plus_tool": ["--version"],
    "mp4box": ["-version"],
    "handbrake": ["--version"],
    "rmts": [],
}


TOOL_FEATURE_LABELS: dict[str, list[str]] = {
    "ffprobe": ["Analyse/JSON"],
    "mkvmerge": ["MKV-Mux"],
    "mkvextract": ["MKV-Extraktion"],
    "makemkvcon": ["ISO/Disc-Extraktion"],
    "mediainfo": ["MediaInfo-Analyse", "HDR/DV-Erkennung"],
    "dovi_tool": ["Dolby-Vision-RPU"],
    "hdr10plus_tool": ["HDR10+-Metadaten"],
    "mp4box": ["MP4/DV-Mux"],
    "handbrake": ["Externe GUI/CLI"],
    "rmts": ["Serien-Umbenennung"],
}


def _exists_or_which(path: str) -> bool:
    value = str(path or "").strip()
    if not value:
        return False
    return Path(value).exists() or bool(shutil.which(value))


def _run_tool(path: str, args: list[str], *, timeout: int = 5) -> tuple[int, str]:
    if not args:
        return 0, ""
    try:
        result = subprocess.run(
            [path, *args],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            **subprocess_no_window_kwargs(),
        )
        text = "\n".join(part for part in (result.stdout, result.stderr) if part)
        return int(result.returncode), text.strip()
    except Exception as exc:
        return 1, str(exc)


CommandRunner = Callable[[list[str], int], tuple[int, str]]


def _run_command(cmd: list[str], timeout: int = 15) -> tuple[int, str]:
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=timeout,
            stdin=subprocess.DEVNULL,
            **subprocess_no_window_kwargs(),
        )
        text = "\n".join(part for part in (result.stdout, result.stderr) if part)
        return int(result.returncode), text.strip()
    except Exception as exc:
        return 1, str(exc)


def _first_useful_line(text: str) -> str:
    for line in (text or "").splitlines():
        clean = line.strip()
        if clean:
            return clean
    return ""


def _probe_ffmpeg_features(path: str) -> list[str]:
    features: list[str] = []
    _rc, filters_text = _run_tool(path, ["-hide_banner", "-filters"], timeout=6)
    filters = filters_text.lower()
    if "libplacebo" in filters:
        features.append("libplacebo")
    if "zscale" in filters:
        features.append("zscale")
    if " subtitles " in filters or " ass " in filters:
        features.append("Untertitel/Burn-In")

    _rc, encoders_text = _run_tool(path, ["-hide_banner", "-encoders"], timeout=6)
    encoders = encoders_text.lower()
    has_nvenc = "hevc_nvenc" in encoders or "h264_nvenc" in encoders or "av1_nvenc" in encoders
    if has_nvenc:
        features.append("NVENC")
        _rc, nvenc_help = _run_tool(path, ["-hide_banner", "-h", "encoder=hevc_nvenc"], timeout=6)
        nvenc_help_l = nvenc_help.lower()
        if "-lookahead_level" in nvenc_help_l:
            features.append("NVENC lookahead_level")
        if "-multipass" in nvenc_help_l:
            features.append("NVENC multipass")
    if "hevc_qsv" in encoders or "h264_qsv" in encoders or "av1_qsv" in encoders:
        features.append("QSV")
    if "hevc_amf" in encoders or "h264_amf" in encoders or "av1_amf" in encoders:
        features.append("AMF")
    if "libx265" in encoders:
        features.append("x265")
    if "libsvtav1" in encoders or "av1_svt" in encoders:
        features.append("SVT-AV1")
        _rc, svt_help = _run_tool(path, ["-hide_banner", "-h", "encoder=libsvtav1"], timeout=6)
        if "dolbyvision" in svt_help.lower():
            features.append("AV1 Dolby Vision P10")
    if "libaom-av1" in encoders:
        features.append("libaom-av1 / AV1 HDR10+")
    return features


def probe_tool(tool_name: str, path: str) -> dict[str, Any]:
    found = _exists_or_which(path)
    info: dict[str, Any] = {
        "name": tool_name,
        "path": path,
        "found": found,
        "version": "",
        "features": [],
        "error": "",
    }
    if not found:
        return info

    args = TOOL_VERSION_ARGS.get(tool_name, ["--version"])
    if tool_name == "handbrake" and "cli" not in Path(path).stem.lower():
        args = []
    rc, text = _run_tool(path, args)
    if rc == 0 or text:
        info["version"] = _first_useful_line(text)
    if rc != 0 and text:
        info["error"] = _first_useful_line(text)

    if tool_name == "ffmpeg":
        info["features"] = _probe_ffmpeg_features(path)
    else:
        info["features"] = list(TOOL_FEATURE_LABELS.get(tool_name, []))
    return info


def build_tool_diagnostics(tool_paths: dict[str, str]) -> list[dict[str, Any]]:
    return [probe_tool(name, path) for name, path in tool_paths.items()]


def _path_for(tool_paths: dict[str, str], key: str) -> str:
    value = str(tool_paths.get(key) or "").strip()
    if not value or not _exists_or_which(value):
        return ""
    return value


def _mini_row(name: str, ok: bool, detail: str, *, skipped: bool = False) -> dict[str, Any]:
    return {
        "name": name,
        "ok": bool(ok),
        "skipped": bool(skipped),
        "detail": detail,
    }


def _file_ok(path: Path) -> bool:
    try:
        return path.exists() and path.stat().st_size > 0
    except OSError:
        return False


def _duration_ok(text: str) -> bool:
    try:
        return float(str(text).splitlines()[0].strip()) > 0
    except (IndexError, TypeError, ValueError):
        return False


def run_extended_system_test(
    tool_paths: dict[str, str],
    *,
    runner: CommandRunner | None = None,
) -> list[dict[str, Any]]:
    from .tool_diagnostics_extended import run_extended_system_test as _run_extended
    return _run_extended(tool_paths, runner=runner, path_exists=_exists_or_which)

def format_tool_diagnostics(rows: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    for row in rows:
        name = str(row.get("name") or "")
        path = str(row.get("path") or "")
        if not row.get("found"):
            lines.append(f"❌  {name}  (nicht gefunden)")
            continue
        lines.append(f"✅  {name}")
        lines.append(f"   Pfad: {path}")
        version = str(row.get("version") or "").strip()
        if version:
            lines.append(f"   Version: {version}")
        features = [str(v) for v in row.get("features") or [] if v]
        if features:
            lines.append(f"   Features: {', '.join(features)}")
        error = str(row.get("error") or "").strip()
        if error and not version:
            lines.append(f"   Hinweis: {error}")
    return "\n".join(lines)


def format_extended_system_test(rows: list[dict[str, Any]]) -> str:
    lines = ["Erweiterter Systemtest mit Mini-Dateien", ""]
    for row in rows:
        if row.get("skipped"):
            prefix = "⚠️"
        else:
            prefix = "✅" if row.get("ok") else "❌"
        lines.append(f"{prefix}  {row.get('name', '')}")
        detail = str(row.get("detail") or "").strip()
        if detail:
            lines.append(f"   {detail}")
    return "\n".join(lines).strip()
