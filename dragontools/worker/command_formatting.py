from __future__ import annotations

from pathlib import Path


def is_ffmpeg_command(cmd0: str) -> bool:
    return Path(cmd0).stem.lower() == "ffmpeg"


def command_to_log_string(cmd: list) -> str:
    parts = []
    for c in cmd:
        s = str(c)
        if " " in s or (":" in s and len(s) > 2):
            parts.append(f'"{s}"')
        else:
            parts.append(s)
    return " ".join(parts)
