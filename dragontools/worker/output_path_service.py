# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import threading
from pathlib import Path


_RESERVED_OUTPUT_PATHS: set[str] = set()
_RESERVED_OUTPUT_PATHS_LOCK = threading.Lock()


class OutputPathService:
    """Bestimmt Ausgabepfade für Standard- und Overwrite-Läufe."""

    def __init__(self, *, codec: str, overwrite_original: bool) -> None:
        self._codec = codec
        self._overwrite_original = overwrite_original

    def resolve_output_path(self, input_path: str, container: str) -> tuple[Path, str]:
        stem = Path(input_path).stem
        base_dir = Path(input_path).parent
        tag = {"h264": "H264", "h265": "H265", "av1": "AV1"}.get(
            self._codec, self._codec.upper()
        )
        if self._overwrite_original:
            tmp_dir = self.temp_overwrite_dir(base_dir)
            tmp_dir.mkdir(exist_ok=True)
            output_path = str(_reserve_unique_output_path(tmp_dir / f"{stem}.{container}"))
        else:
            candidate = base_dir / f"{stem}_{tag}.{container}"
            output_path = str(_reserve_unique_output_path(candidate))
        return base_dir, output_path

    def temp_overwrite_dir(self, base_dir: Path) -> Path:
        return base_dir / "__temp_overwrite__"


def release_output_path_reservation(path: str | Path | None) -> None:
    if not path:
        return
    with _RESERVED_OUTPUT_PATHS_LOCK:
        _RESERVED_OUTPUT_PATHS.discard(_reservation_key(Path(path)))


def _reserve_unique_output_path(candidate: Path) -> Path:
    with _RESERVED_OUTPUT_PATHS_LOCK:
        current = candidate
        counter = 1
        while current.exists() or _reservation_key(current) in _RESERVED_OUTPUT_PATHS:
            current = candidate.with_name(f"{candidate.stem}_{counter}{candidate.suffix}")
            counter += 1
        _RESERVED_OUTPUT_PATHS.add(_reservation_key(current))
        return current


def _reservation_key(path: Path) -> str:
    return os.path.normcase(os.path.abspath(str(path)))
