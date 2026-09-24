# -*- coding: utf-8 -*-
"""Live tool diagnostics for unsaved settings-dialog values."""
from __future__ import annotations

from pathlib import Path

from ..core.settings_storage import TOOL_KEYS
from ..core.tool_diagnostics import build_tool_diagnostics, format_tool_diagnostics
from ..core.tool_paths import ToolPathSettingsProvider, ToolPaths, find_tool
from ..core.whisper_runtime import build_whisper_diagnostic
from .tool_diagnostics_dialog import show_tool_diagnostics_dialog


class _CurrentToolPathProvider(ToolPathSettingsProvider):
    """Resolve tools from the QLineEdit snapshot without touching QSettings."""

    def __init__(self, values: dict[str, str]) -> None:
        self._dirs = {
            tool: str(values.get(dir_key) or "").strip()
            for tool, (_use_key, dir_key) in TOOL_KEYS.items()
        }

    def get_custom_dirs(self) -> list[Path]:
        return [Path(value) for value in self._dirs.values() if value and Path(value).exists()]

    def find_in_settings(self, tool_key: str, *exe_names: str) -> str | None:
        value = self._dirs.get(tool_key, "")
        if not value:
            return None
        root = Path(value)
        if root.is_file():
            if root.name.casefold() in {name.casefold() for name in exe_names}:
                return str(root)
            return None
        for name in exe_names:
            candidate = root / name
            if candidate.is_file():
                return str(candidate)
        try:
            for child in root.iterdir():
                if not child.is_dir():
                    continue
                for name in exe_names:
                    candidate = child / name
                    if candidate.is_file():
                        return str(candidate)
        except OSError:
            return None
        return None


def _resolve(provider: _CurrentToolPathProvider, tool_key: str, *names: str) -> str:
    configured = provider.find_in_settings(tool_key, *names)
    if configured:
        return configured
    return find_tool(*names)


def _tool_props(provider: _CurrentToolPathProvider) -> dict[str, str]:
    optional_tools = ToolPaths(provider=provider)
    return {
        "ffmpeg": _resolve(provider, "ffmpeg", "ffmpeg.exe", "ffmpeg"),
        "ffprobe": _resolve(provider, "ffmpeg", "ffprobe.exe", "ffprobe"),
        "mkvmerge": _resolve(provider, "mkv", "mkvmerge.exe", "mkvmerge"),
        "mkvextract": _resolve(provider, "mkv", "mkvextract.exe", "mkvextract"),
        "mkvpropedit": _resolve(provider, "mkv", "mkvpropedit.exe", "mkvpropedit"),
        "makemkvcon": _resolve(provider, "makemkvcon", "makemkvcon64.exe", "makemkvcon.exe", "makemkvcon"),
        "rmts": _resolve(provider, "rmts", "RenameMyTVSeries.exe", "rmts.exe", "RenameMyTVSeries"),
        "handbrake": _resolve(provider, "handbrake", "HandBrake.exe", "HandBrake"),
        "mediainfo": _resolve(provider, "mediainfo", "MediaInfo.exe", "mediainfo.exe", "mediainfo"),
        "dovi_tool": _resolve(provider, "dovi_tool", "dovi_tool.exe", "dovi_tool"),
        "hdr10plus_tool": _resolve(provider, "hdr10plus_tool", "hdr10plus_tool.exe", "hdr10plus_tool"),
        "hdr10plus_generator": optional_tools.hdr10plus_generator,
        "davinci_resolve": optional_tools.davinci_resolve,
        "comfyui": optional_tools.comfyui,
        "mp4box": _resolve(provider, "mp4box", "MP4Box.exe", "mp4box.exe", "MP4Box", "mp4box"),
        "tesseract": _resolve(provider, "tesseract", "tesseract.exe", "tesseract"),
    }


def run_live_tool_check(
    parent,
    *,
    tool_edits: dict[str, object],
    whisper_model_dir: str = "",
    whisper_use_local_model: bool = False,
    whisper_model_name: str = "small",
) -> None:
    values = {
        key: str(edit.text()).strip()
        for key, edit in tool_edits.items()
        if hasattr(edit, "text")
    }
    provider = _CurrentToolPathProvider(values)
    rows = build_tool_diagnostics(_tool_props(provider))
    rows.append(
        build_whisper_diagnostic(
            whisper_model_dir,
            use_local_model=whisper_use_local_model,
            model_name=whisper_model_name,
        )
    )
    show_tool_diagnostics_dialog(
        parent,
        title="Werkzeugpfade prüfen",
        text=format_tool_diagnostics(rows) or "Keine Tools konfiguriert.",
    )


__all__ = ["run_live_tool_check"]
