# -*- coding: utf-8 -*-
"""Sidecar- und Trickplay-Verschiebung als eigener Service."""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from .move_file_service import new_move_result
from .move_conflicts import same_path
from .move_transaction import PathSwapTransaction, PathTransactionRollbackError, remove_path


class MoveSidecarService:
    def __init__(
        self,
        *,
        filme_path: str,
        trickplay_conflict_mode: str,
        nfo_movie_target_name: str,
        move_file: Callable[..., tuple[bool, dict]],
        log: Callable[[str, str], None],
        append_report: Callable[[dict | None, str, str | None], None],
        set_last_result: Callable[[dict], None],
    ) -> None:
        self.filme_path = filme_path
        self.trickplay_conflict_mode = trickplay_conflict_mode
        self.nfo_movie_target_name = nfo_movie_target_name
        self._move_file = move_file
        self._log = log
        self._append_report = append_report
        self._set_last_result = set_last_result

    def move_sidecars(self, video_path: str, target_dir: str, sidecars: list[str]) -> dict:
        """Verschiebt Companion-Dateien idempotent und liefert einen Gesamtstatus.

        Ein fehlender Quell-Sidecar gilt bei einer Wiederaufnahme als bereits
        abgeschlossen, wenn der erwartete Zielpfad existiert. Damit kann ein
        Crash nach einzelnen Sidecar-Commits sicher fortgesetzt werden.
        """
        summary = {
            "ok": True,
            "total": 0,
            "moved": 0,
            "already_present": 0,
            "failed": 0,
            "results": [],
        }
        for sidecar in sidecars or []:
            summary["total"] += 1
            sidecar_p = Path(sidecar)
            sidecar_type = self.sidecar_type(sidecar_p)
            dest_name = self.sidecar_dest_name(sidecar_p, target_dir)
            dest_path = Path(target_dir) / dest_name

            if not sidecar_p.exists():
                if dest_path.exists():
                    result = {
                        "kind": "sidecar",
                        "sidecar_type": sidecar_type,
                        "name": sidecar_p.name,
                        "source_path": str(sidecar_p),
                        "target_dir": str(target_dir),
                        "dest_path": str(dest_path),
                        "ok": True,
                        "already_present": True,
                        "conflict": False,
                        "deleted_existing": False,
                        "replaced_existing": False,
                        "renamed": False,
                        "skipped_conflict": False,
                    }
                    summary["already_present"] += 1
                    summary["results"].append(result)
                    self._append_report(result, "sidecar", sidecar_type)
                    self._log(f"  ✅ Sidecar bereits im Ziel: {dest_name}", "info")
                    continue

                result = {
                    "kind": "sidecar",
                    "sidecar_type": sidecar_type,
                    "name": sidecar_p.name,
                    "source_path": str(sidecar_p),
                    "target_dir": str(target_dir),
                    "dest_path": str(dest_path),
                    "ok": False,
                    "conflict": False,
                    "deleted_existing": False,
                    "replaced_existing": False,
                    "renamed": False,
                    "skipped_conflict": False,
                }
                summary["ok"] = False
                summary["failed"] += 1
                summary["results"].append(result)
                self._log(f"  ⚠️ Sidecar nicht gefunden: {sidecar_p.name}", "warn")
                self._append_report(result, "sidecar", sidecar_type)
                continue

            if sidecar_type == "trickplay" and sidecar_p.is_dir():
                ok, result = self.move_trickplay(sidecar_p, dest_path)
                self._set_last_result(result)
                self._append_report(result, "sidecar", sidecar_type)
                summary["results"].append(result)
                if ok:
                    summary["moved"] += 1
                    if result.get("skipped_conflict"):
                        self._log(f"  🧩 Trickplay im Ziel beibehalten: {dest_name}", "info")
                    elif dest_name != sidecar_p.name:
                        self._log(f"  🧩 Trickplay verschoben: {sidecar_p.name} -> {dest_name}", "info")
                    else:
                        self._log(f"  🧩 Trickplay verschoben: {sidecar_p.name}", "info")
                else:
                    summary["ok"] = False
                    summary["failed"] += 1
                    self._log(f"  ❌ Trickplay konnte nicht verschoben werden: {sidecar_p.name}", "error")
                continue

            ok, result = self._move_file(sidecar, target_dir, dest_name=dest_name)
            self._set_last_result(result)
            self._append_report(result, "sidecar", sidecar_type)
            summary["results"].append(result)
            if ok:
                summary["moved"] += 1
                if dest_name != sidecar_p.name:
                    self._log(f"  📄 Sidecar verschoben: {sidecar_p.name} -> {dest_name}", "info")
                else:
                    self._log(f"  📄 Sidecar verschoben: {sidecar_p.name}", "info")
            else:
                summary["ok"] = False
                summary["failed"] += 1
                self._log(f"  ❌ Sidecar konnte nicht verschoben werden: {sidecar_p.name}", "error")

        return summary

    def move_trickplay(self, src_p: Path, dst_p: Path) -> tuple[bool, dict]:
        result = new_move_result(str(src_p), str(dst_p.parent), dest_name=dst_p.name)
        transaction: PathSwapTransaction | None = None
        try:
            dst_p.parent.mkdir(parents=True, exist_ok=True)
            result["target_dir"] = str(dst_p.parent)
            result["dest_path"] = str(dst_p)
            if dst_p.exists() and same_path(src_p, dst_p):
                result["ok"] = True
                self._log(f"ℹ️ Trickplay liegt bereits im Zielordner: {dst_p.name}", "info")
                return True, result

            if not dst_p.exists():
                shutil.move(str(src_p), str(dst_p))
                result["ok"] = True
                return True, result

            mode = self.trickplay_conflict_mode
            result["conflict"] = True
            result["conflict_paths"] = [str(dst_p)]
            if mode == "skip":
                result["ok"] = True
                result["skipped_conflict"] = True
                self._log(f"  🧩 Trickplay im Ziel vorhanden, wird behalten: {dst_p.name}", "info")
                try:
                    remove_path(src_p)
                except (OSError, shutil.Error) as exc:
                    self._log(f"⚠️ Nicht benötigte Trickplay-Quelle konnte nicht entfernt werden: {exc}", "warn")
                return True, result

            if mode not in {"backup", "overwrite"}:
                raise ValueError(f"Unbekannter Trickplay-Konfliktmodus: {mode}")

            backup_mode = mode == "backup"
            backup_p = self.unique_trickplay_backup_path(dst_p) if backup_mode else self.unique_overwrite_backup_path(dst_p)
            transaction = PathSwapTransaction(src_p, dst_p, backup_p)
            transaction.stage()
            transaction.commit()
            self._remove_committed_source(src_p)
            result["ok"] = True
            result["dest_path"] = str(dst_p)

            if backup_mode:
                result["backed_up_existing"] = True
                result["backed_up_existing_count"] = 1
                self._log(f"  🧩 Vorhandene Trickplaybilder gesichert: {backup_p.name}", "info")
            else:
                result["replaced_existing"] = True
                result["replaced_existing_count"] = 1
                try:
                    transaction.discard_backup()
                except (OSError, shutil.Error) as cleanup_exc:
                    self._log(
                        f"⚠️ Altes Trickplay-Backup konnte nach erfolgreichem Commit nicht entfernt werden: {cleanup_exc}",
                        "warn",
                    )
                self._log(f"  🧩 Vorhandene Trickplaybilder transaktional ersetzt: {dst_p.name}", "info")
            return True, result
        except (OSError, shutil.Error, PathTransactionRollbackError, ValueError, RuntimeError) as exc:
            self._log(f"❌ Fehler beim Verschieben der Trickplaybilder: {exc}", "error")
            if transaction is not None:
                transaction.cleanup_staging(best_effort=True)
                if transaction.backup_created and not dst_p.exists():
                    try:
                        transaction.rollback()
                        self._log(f"↩️ Vorhandene Trickplaybilder wiederhergestellt: {dst_p.name}", "warn")
                    except (OSError, shutil.Error) as rollback_exc:
                        self._log(
                            "❌ Trickplay-Rollback unvollständig; Backup bleibt erhalten: "
                            f"{transaction.backup_path} – {rollback_exc}",
                            "error",
                        )
            return False, result

    @staticmethod
    def sidecar_type(sidecar_p: Path) -> str:
        suffix = sidecar_p.suffix.lower()
        if suffix == ".trickplay":
            return "trickplay"
        if suffix == ".nfo":
            return "nfo"
        if suffix in {".srt", ".ass", ".ssa", ".sup", ".sub", ".idx", ".vtt"}:
            return "subtitle"
        return "sidecar"

    def sidecar_dest_name(self, sidecar_p: Path, target_dir: str) -> str:
        if sidecar_p.suffix.lower() != ".nfo" or not self.is_film_target(target_dir):
            return sidecar_p.name
        configured = str(self.nfo_movie_target_name or "").strip()
        if configured == "stem":
            return sidecar_p.name
        return configured or "movie.nfo"

    def is_film_target(self, target_dir: str) -> bool:
        if not self.filme_path:
            return False
        try:
            target = Path(target_dir).resolve()
            films = Path(self.filme_path).resolve()
            return target == films or films in target.parents
        except OSError:
            return False

    @staticmethod
    def unique_trickplay_backup_path(dst_p: Path) -> Path:
        candidate = dst_p.with_name(f"{dst_p.name}.bak")
        if not candidate.exists():
            return candidate
        for idx in range(1, 1000):
            numbered = dst_p.with_name(f"{dst_p.name}.bak_{idx:02d}")
            if not numbered.exists():
                return numbered
        raise RuntimeError(f"Kein freier Backup-Ordner gefunden für {dst_p.name}")

    @staticmethod
    def unique_overwrite_backup_path(dst_p: Path) -> Path:
        import uuid
        token = uuid.uuid4().hex[:10]
        return dst_p.with_name(f"{dst_p.name}.__dragontools_backup__{token}")

    def _remove_committed_source(self, src_p: Path) -> None:
        try:
            if src_p.exists() or src_p.is_symlink():
                remove_path(src_p)
        except (OSError, shutil.Error) as exc:
            self._log(f"⚠️ Ziel ist vollständig vorhanden, Quelle konnte aber nicht entfernt werden: {exc}", "warn")
