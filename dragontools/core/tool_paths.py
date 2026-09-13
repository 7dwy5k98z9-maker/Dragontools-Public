# -*- coding: utf-8 -*-
"""Discovery, caching and settings integration for external executables."""
from __future__ import annotations

import os
import shutil
import threading
from abc import ABC, abstractmethod
from pathlib import Path

from .resource_paths import BASE, EXE_DIR, known_tool_dirs


class ToolPathSettingsProvider(ABC):
    """Qt-free provider contract for user configured tool directories."""

    @abstractmethod
    def get_custom_dirs(self) -> list[Path]:
        """Return configured tool directories that currently exist."""

    @abstractmethod
    def find_in_settings(self, tool_key: str, *exe_names: str) -> str | None:
        """Return a configured executable path or ``None``."""


def extend_path(
    extra: list[Path] | None = None,
    *,
    base: Path | None = None,
    exe_dir: Path | None = None,
) -> None:
    """Prepend existing known tool directories to PATH, deduplicated."""
    candidates = known_tool_dirs(base=base, exe_dir=exe_dir)
    if extra:
        candidates.extend(extra)

    new_dirs: list[str] = []
    for path in candidates:
        try:
            if path.exists():
                new_dirs.append(str(path.resolve()))
        except OSError:
            continue

    current_parts = [part for part in os.environ.get("PATH", "").split(os.pathsep) if part]
    normalized_existing: set[str] = set()
    cleaned_current: list[str] = []
    for part in current_parts:
        try:
            normalized = str(Path(part).resolve())
        except OSError:
            normalized = part
        if normalized not in normalized_existing:
            normalized_existing.add(normalized)
            cleaned_current.append(part)

    to_add: list[str] = []
    for path in new_dirs:
        if path not in normalized_existing:
            normalized_existing.add(path)
            to_add.append(path)
    os.environ["PATH"] = os.pathsep.join(to_add + cleaned_current)


def _resolve_tool_candidate(path: Path, executable_names: tuple[str, ...]) -> str | None:
    try:
        if path.is_file():
            return str(path)
        if path.is_dir():
            for name in executable_names:
                nested = path / name
                if nested.is_file():
                    return str(nested)
    except OSError:
        return None
    return None


def find_tool(
    name: str,
    *alt_names: str,
    base: Path | None = None,
    exe_dir: Path | None = None,
) -> str:
    """Find an executable in PATH and deterministic DragonTools tool folders."""
    found = shutil.which(name)
    if not found:
        for alternate in alt_names:
            found = shutil.which(alternate)
            if found:
                break
    if found:
        return found

    executable_names = (name, *alt_names)
    for root in known_tool_dirs(base=base, exe_dir=exe_dir):
        for candidate_name in executable_names:
            resolved = _resolve_tool_candidate(root / candidate_name, executable_names)
            if resolved:
                return resolved
    return name


class ToolPaths:
    """Cached access to all external executables used by DragonTools."""

    def __init__(self, provider: ToolPathSettingsProvider | None = None) -> None:
        self._provider = provider
        extend_path(extra=provider.get_custom_dirs() if provider is not None else None)
        self._cache: dict[str, str] = {}

    def _find(self, tool_key: str, *names: str) -> str:
        cache_key = f"{tool_key}:{'|'.join(names)}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        result: str | None = None
        if self._provider is not None:
            result = self._provider.find_in_settings(tool_key, *names)
            if result:
                result = _resolve_tool_candidate(Path(result), names)
        if not result:
            result = find_tool(*names)
        self._cache[cache_key] = result
        return result

    def find_in_settings(self, tool_key: str, *exe_names: str) -> str | None:
        if self._provider is None:
            return None
        return self._provider.find_in_settings(tool_key, *exe_names)

    @property
    def ffmpeg(self) -> str:
        return self._find("ffmpeg", "ffmpeg.exe", "ffmpeg")

    @property
    def ffprobe(self) -> str:
        return self._find("ffmpeg", "ffprobe.exe", "ffprobe")

    @property
    def mkvmerge(self) -> str:
        return self._find("mkv", "mkvmerge.exe", "mkvmerge")

    @property
    def makemkvcon(self) -> str:
        return self._find("makemkvcon", "makemkvcon64.exe", "makemkvcon.exe", "makemkvcon")

    @property
    def mkvextract(self) -> str:
        return self._find("mkv", "mkvextract.exe", "mkvextract")

    @property
    def mkvinfo(self) -> str:
        return self._find("mkv", "mkvinfo.exe", "mkvinfo")

    @property
    def mkvpropedit(self) -> str:
        return self._find("mkv", "mkvpropedit.exe", "mkvpropedit")

    @property
    def mediainfo(self) -> str:
        return self._find("mediainfo", "MediaInfo.exe", "mediainfo.exe", "mediainfo", "MediaInfo")

    @property
    def dovi_tool(self) -> str:
        return self._find("dovi_tool", "dovi_tool.exe", "dovi_tool")

    @property
    def hdr10plus_tool(self) -> str:
        return self._find("hdr10plus_tool", "hdr10plus_tool.exe", "hdr10plus_tool")

    @property
    def mp4box(self) -> str:
        return self._find("mp4box", "MP4Box.exe", "mp4box.exe", "MP4Box", "mp4box")

    @property
    def handbrake_cli(self) -> str:
        return self._find(
            "handbrake", "HandBrake.exe", "HandBrakeCLI.exe", "HandBrake", "HandBrakeCLI", "handbrake_cli"
        )

    @property
    def rmts(self) -> str:
        return self._find("rmts", "RenameMyTVSeries.exe", "rmts.exe", "RenameMyTVSeries")

    def verify_all(self) -> dict[str, bool]:
        tools = {
            "ffmpeg": self.ffmpeg,
            "ffprobe": self.ffprobe,
            "mkvmerge": self.mkvmerge,
            "makemkvcon": self.makemkvcon,
            "mkvextract": self.mkvextract,
            "rmts": self.rmts,
            "handbrake": self.handbrake_cli,
            "mediainfo": self.mediainfo,
            "dovi_tool": self.dovi_tool,
            "hdr10plus_tool": self.hdr10plus_tool,
            "mp4box": self.mp4box,
        }
        return {
            name: (Path(path).exists() or bool(shutil.which(path)))
            for name, path in tools.items()
        }


_tool_paths_instance: ToolPaths | None = None
_tool_paths_provider: ToolPathSettingsProvider | None = None
_tool_paths_lock = threading.Lock()


def get_tool_paths(provider: ToolPathSettingsProvider | None = None) -> ToolPaths:
    """Return the process-wide, thread-safe ToolPaths instance."""
    global _tool_paths_instance, _tool_paths_provider
    if _tool_paths_instance is not None:
        return _tool_paths_instance
    with _tool_paths_lock:
        if _tool_paths_instance is None:
            if provider is not None:
                _tool_paths_provider = provider
            _tool_paths_instance = ToolPaths(provider=_tool_paths_provider)
        return _tool_paths_instance


def invalidate_tool_paths() -> None:
    """Drop cached executable resolutions while preserving the provider."""
    global _tool_paths_instance
    with _tool_paths_lock:
        _tool_paths_instance = None


def find_tool_in_settings(tool_key: str, *exe_names: str) -> str | None:
    """Compatibility helper for legacy GUI call sites."""
    return get_tool_paths().find_in_settings(tool_key, *exe_names)


__all__ = [
    "ToolPathSettingsProvider", "ToolPaths", "extend_path", "find_tool",
    "get_tool_paths", "invalidate_tool_paths", "find_tool_in_settings",
]
