# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from .duration_repair_runtime import DurationRepairRuntime


def format_duration(seconds: float | None) -> str:
    if seconds is None:
        return "unbekannt"
    try:
        return f"{float(seconds):.1f}s"
    except (TypeError, ValueError):
        return "unbekannt"


def unique_archive_path(archive_dir: Path, filename: str) -> Path:
    candidate = archive_dir / filename
    if not candidate.exists():
        return candidate
    stem = candidate.stem
    suffix = candidate.suffix
    counter = 1
    while True:
        numbered = archive_dir / f"{stem}_{counter}{suffix}"
        if not numbered.exists():
            return numbered
        counter += 1


class DurationRepairArchive:
    def __init__(self, runtime: DurationRepairRuntime) -> None:
        self._runtime = runtime

    def archive(self, output_path: Path, base_dir: Path | None) -> str | None:
        if not output_path.exists():
            return None
        root = Path(base_dir) if base_dir is not None else output_path.parent
        archive_dir = root / "Archiv"
        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
            target = unique_archive_path(archive_dir, output_path.name)
            self._runtime.replace_file(output_path, target)
            self._runtime.log(
                "📦 Datei aufgrund weiterhin fehlerhafter Laufzeit in den Archiv-Ordner verschoben: "
                f"{target}",
                "warn",
            )
            return str(target)
        except Exception as exc:
            self._runtime.log(
                f"❌ Archivierung der fehlerhaften Ausgabedatei fehlgeschlagen: {exc}",
                "error",
            )
            return None
