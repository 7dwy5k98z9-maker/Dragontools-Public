# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from .duration_repair_archive import unique_archive_path


class RejectedTimestampArchive:
    def __init__(self, runtime) -> None:
        self._runtime = runtime

    def archive(self, tmp: Path, *, out: Path, base_dir: Path | None, label: str, reason: str) -> str | None:
        if not tmp.exists():
            self._runtime.safe_unlink(tmp)
            return None
        try:
            root = Path(base_dir) if base_dir is not None else self.archive_root_for(out)
            archive_dir = root / "Archiv" / "Timestamp_Reparatur"
            archive_dir.mkdir(parents=True, exist_ok=True)
            target = unique_archive_path(archive_dir, f"{out.stem}.{self.safe_label(label)}{out.suffix}")
            self._runtime.replace_file(tmp, target)
            self._runtime.log(
                "📦 Verworfener Timestamp-Reparaturkandidat wurde zur Prüfung archiviert: "
                f"{target} ({reason})",
                "warn",
            )
            return str(target)
        except (OSError, RuntimeError, AttributeError) as exc:
            self._runtime.log(f"⚠️ Verworfener Timestamp-Reparaturkandidat konnte nicht archiviert werden: {exc}", "warn")
            self._runtime.safe_unlink(tmp)
            return None

    @staticmethod
    def archive_root_for(out: Path) -> Path:
        if out.parent.name.lower() == "__temp_overwrite__" and out.parent.parent != out.parent:
            return out.parent.parent
        return out.parent

    @staticmethod
    def safe_label(label: str) -> str:
        cleaned = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in str(label))
        return cleaned.strip("._-") or "Timestamp-Reparatur"
