"""Reserve and recognize direct-DV staging paths without touching other jobs."""
from __future__ import annotations

import re
from pathlib import Path


def reserve_output_path(candidate: Path) -> Path:
    counter = 0
    while True:
        path = candidate if counter == 0 else candidate.with_name(f"{candidate.stem}_{counter}{candidate.suffix}")
        try:
            with path.open("xb"):
                pass
            return path
        except FileExistsError:
            counter += 1


def is_known_staging_path(source: Path, candidate: Path, *, container: str, overwrite: bool, owned: Path | None) -> bool:
    try:
        if candidate.is_symlink() or candidate.resolve() == source.resolve():
            return False
        if owned is not None:
            return candidate.resolve() == owned.resolve()
        # Compatibility for legacy callers that supply a staging path directly.
        # Exact generated names replace the old directory/prefix-only test.
        directory = source.parent / "__temp_dv_remux__" if overwrite else source.parent
        stem = source.stem if overwrite else source.stem + "_DV_Remux"
        pattern = re.escape(stem) + r"(?:_[1-9][0-9]*)?" + re.escape("." + container)
        return candidate.resolve().parent == directory.resolve() and re.fullmatch(pattern, candidate.name) is not None
    except OSError:
        return False
