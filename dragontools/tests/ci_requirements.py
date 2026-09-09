from __future__ import annotations

import importlib.util
import os
import shutil
from dataclasses import dataclass
from pathlib import Path


_TRUTHY = {"1", "true", "yes", "on"}


def env_flag(name: str) -> bool:
    return os.environ.get(name, "").strip().casefold() in _TRUTHY


@dataclass(frozen=True, slots=True)
class ExternalMediaEnvironment:
    ffmpeg: str | None
    ffprobe: str | None
    dovi_tool: str | None
    hdr10plus_tool: str | None
    mp4box: str | None
    @property
    def missing(self) -> tuple[str, ...]:
        missing: list[str] = []
        for label, value in (
            ("ffmpeg", self.ffmpeg),
            ("ffprobe", self.ffprobe),
            ("dovi_tool", self.dovi_tool),
            ("hdr10plus_tool", self.hdr10plus_tool),
            ("MP4Box", self.mp4box),
        ):
            if not value:
                missing.append(label)
        return tuple(missing)


def missing_qt_dependencies() -> tuple[str, ...]:
    missing: list[str] = []
    for module_name, label in (("PyQt6", "PyQt6"), ("pytestqt", "pytest-qt")):
        try:
            found = importlib.util.find_spec(module_name) is not None
        except (ImportError, ValueError):
            found = False
        if not found:
            missing.append(label)
    return tuple(missing)


def _resolve_tool(env_name: str, *names: str) -> str | None:
    configured = os.environ.get(env_name, "").strip()
    if configured:
        path = Path(configured).expanduser()
        if path.is_file():
            return str(path.resolve())
        # Accept command names supplied through the variable as well.
        found = shutil.which(configured)
        return found
    for name in names:
        found = shutil.which(name)
        if found:
            return found
    return None



def external_media_environment() -> ExternalMediaEnvironment:
    return ExternalMediaEnvironment(
        ffmpeg=_resolve_tool("DRAGONTOOLS_FFMPEG", "ffmpeg", "ffmpeg.exe"),
        ffprobe=_resolve_tool("DRAGONTOOLS_FFPROBE", "ffprobe", "ffprobe.exe"),
        dovi_tool=_resolve_tool("DRAGONTOOLS_DOVI_TOOL", "dovi_tool", "dovi_tool.exe"),
        hdr10plus_tool=_resolve_tool(
            "DRAGONTOOLS_HDR10PLUS_TOOL", "hdr10plus_tool", "hdr10plus_tool.exe"
        ),
        mp4box=_resolve_tool("DRAGONTOOLS_MP4BOX", "MP4Box", "MP4Box.exe", "mp4box"),
    )
