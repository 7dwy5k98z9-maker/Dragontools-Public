from __future__ import annotations

import subprocess
from functools import lru_cache

from ..core.process_runner import subprocess_no_window_kwargs


_PROBE_FILTER = (
    "setparams=range=limited:colorspace=bt709:color_primaries=bt709:color_trc=bt709,"
    "libplacebo=format=p010le"
    ":colorspace=bt2020nc"
    ":color_primaries=bt2020"
    ":color_trc=smpte2084"
    ":range=tv"
    ":inverse_tonemapping=1"
)


@lru_cache(maxsize=8)
def ffmpeg_has_libplacebo(ffmpeg_path: str) -> bool:
    """Prüft nicht nur die Filterliste, sondern eine echte libplacebo-Initialisierung.

    libplacebo kann einkompiliert sein und trotzdem wegen fehlendem/inkompatiblem
    Vulkan-Treiber nicht starten. Für den automatischen Fallback muss genau dieser
    Fall vor dem eigentlichen Encode erkannt werden.
    """
    path = str(ffmpeg_path or "").strip()
    if not path:
        return False
    cmd = [
        path, "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "color=c=gray:size=64x64:rate=1:duration=0.05",
        "-vf", _PROBE_FILTER,
        "-frames:v", "1", "-an", "-sn", "-f", "null", "-",
    ]
    try:
        completed = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            stdin=subprocess.DEVNULL,
            **subprocess_no_window_kwargs(),
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return completed.returncode == 0
