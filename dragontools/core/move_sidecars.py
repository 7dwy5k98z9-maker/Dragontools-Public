# -*- coding: utf-8 -*-
"""Sidecar- und Trickplay-Verschiebung als eigener Service."""
from __future__ import annotations

import filecmp
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
        overwrite_file: Callable[..., tuple[bool, dict]] | None = None,
        log: Callable[[str, str], None],
        append_report: Callable[[dict | None, str, str | None], None],
        set_last_result: Callable[[dict], None],
    ) -> None:
        self.filme_path = filme_path
        self.trickplay_conflict_mode = trickplay_conflict_mode
        self.nfo_movie_target_name = nfo_movie_target_name
        self._move_file = move_file
        self._overwrite_file = overwrite_file or move_file
        self._log = log
        self._append_report = append_report
        self._set_last_result = set_last_result

    def move_sidecars(
        self,
        video_path: str,
        target_dir: str,
        sidecars: list[str],
        *,
        dest_video_path: str | None = None,
        staged_paths: list[str] | tuple[str, ...] | set[str] | None = None,
        force_nfo_overwrite: bool = False,
    ) -> dict:
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
        staged_keys = {self._path_key(path) for path in (staged_paths or [])}
        for sidecar in self._ordered_sidecars(sidecars):
            summary["total"] += 1
            sidecar_p = Path(sidecar)
            sidecar_type = self.sidecar_type(sidecar_p)
            dest_name = self.sidecar_dest_name(
                sidecar_p,
                target_dir,
                video_path=video_path,
                dest_video_path=dest_video_path,
            )
            dest_path = Path(target_dir) / dest_name

            # Companion-first staging copies sidecars into the final location
            # before the video is installed, but intentionally keeps the source
            # until the video commit succeeds.  Finalization consumes that source
            # without treating our own staged copy as a user conflict.
            same_location = bool(
                sidecar_p.exists() and dest_path.exists() and same_path(sidecar_p, dest_path)
            )
            if same_location or (
                dest_path.exists()
                and (
                    self._path_key(dest_path) in staged_keys
                    or (sidecar_p.exists() and self._paths_equivalent(sidecar_p, dest_path))
                )
            ):
                if not same_location:
                    self._remove_committed_source(sidecar_p)
                result = {
                    "kind": "sidecar",
                    "sidecar_type": sidecar_type,
                    "name": sidecar_p.name,
                    "source_path": str(sidecar_p),
                    "target_dir": str(target_dir),
                    "dest_path": str(dest_path),
                    "ok": True,
                    "already_present": True,
                    "staged_before_video": True,
                    "conflict": False,
                    "deleted_existing": False,
                    "replaced_existing": False,
                    "renamed": False,
                    "skipped_conflict": False,
                }
                summary["already_present"] += 1
                summary["results"].append(result)
                self._append_report(result, "sidecar", sidecar_type)
                self._log(f"  ✅ Sidecar vor Video-Commit bereitgestellt: {dest_name}", "info")
                continue

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

            mover = (
                self._overwrite_file
                if force_nfo_overwrite and sidecar_type == "nfo" and dest_path.exists()
                else self._move_file
            )
            ok, result = mover(sidecar, target_dir, dest_name=dest_name)
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

    def stage_before_video(
        self,
        video_path: str,
        target_dir: str,
        sidecars: list[str],
        *,
        dest_video_path: str | None = None,
    ) -> dict:
        """Make companions visible before the video without consuming sources.

        Missing target companions are copied into their final names. Existing
        targets are deliberately left untouched until the video commit succeeds;
        they are still protected from SxxExx cleanup so Jellyfin always sees an
        NFO/subtitle/trickplay companion when the final video appears.
        """
        summary = {
            "ok": True,
            "total": 0,
            "copied": 0,
            "preexisting": 0,
            "failed": 0,
            "protected_paths": [],
            "staged_paths": [],
            "results": [],
        }
        for sidecar in self._ordered_sidecars(sidecars):
            summary["total"] += 1
            source = Path(sidecar)
            sidecar_type = self.sidecar_type(source)
            dest_name = self.sidecar_dest_name(
                source,
                target_dir,
                video_path=video_path,
                dest_video_path=dest_video_path,
            )
            dest = Path(target_dir) / dest_name
            row = {
                "sidecar_type": sidecar_type,
                "source_path": str(source),
                "dest_path": str(dest),
                "status": "",
            }

            if dest.exists():
                row["status"] = "preexisting"
                summary["preexisting"] += 1
                summary["protected_paths"].append(str(dest))
                summary["results"].append(row)
                self._log(
                    f"  🧩 Companion bereits vor Video vorhanden: {dest.name}",
                    "info",
                )
                continue

            if not source.exists():
                row["status"] = "missing"
                summary["ok"] = False
                summary["failed"] += 1
                summary["results"].append(row)
                self._log(
                    f"  ⚠️ Companion vor Video-Commit nicht gefunden: {source.name}",
                    "warn",
                )
                continue

            try:
                dest.parent.mkdir(parents=True, exist_ok=True)
                if source.is_dir():
                    shutil.copytree(str(source), str(dest), copy_function=shutil.copy2)
                else:
                    shutil.copy2(str(source), str(dest))
            except (OSError, shutil.Error) as exc:
                try:
                    if dest.exists() or dest.is_symlink():
                        remove_path(dest)
                except (OSError, shutil.Error):
                    pass
                row["status"] = "error"
                row["message"] = str(exc)
                summary["ok"] = False
                summary["failed"] += 1
                summary["results"].append(row)
                self._log(
                    f"  ❌ Companion konnte vor Video-Commit nicht bereitgestellt werden: "
                    f"{source.name} – {exc}",
                    "error",
                )
                continue

            row["status"] = "copied"
            summary["copied"] += 1
            summary["protected_paths"].append(str(dest))
            summary["staged_paths"].append(str(dest))
            summary["results"].append(row)
            self._log(
                f"  📦 Companion vor Video bereitgestellt: {source.name} -> {dest.name}",
                "info",
            )

        # Stable order and dedupe make the journal/tests deterministic.
        summary["protected_paths"] = list(dict.fromkeys(summary["protected_paths"]))
        summary["staged_paths"] = list(dict.fromkeys(summary["staged_paths"]))
        return summary

    def rollback_stage(self, stage_result: dict | None) -> None:
        """Remove only copies created by :meth:`stage_before_video`."""
        for path_text in reversed(list((stage_result or {}).get("staged_paths") or [])):
            path = Path(path_text)
            try:
                if path.exists() or path.is_symlink():
                    remove_path(path)
                    self._log(
                        f"  ↩️ Vorbereiteter Companion nach fehlgeschlagenem Video-Move entfernt: {path.name}",
                        "warn",
                    )
            except (OSError, shutil.Error) as exc:
                self._log(
                    f"⚠️ Vorbereiteter Companion konnte nicht zurückgerollt werden: {path.name} – {exc}",
                    "warn",
                )

    @classmethod
    def _ordered_sidecars(cls, sidecars: list[str] | tuple[str, ...] | None) -> list[str]:
        priority = {"nfo": 0, "subtitle": 1, "trickplay": 2, "sidecar": 3}
        return sorted(
            list(sidecars or []),
            key=lambda value: (
                priority.get(cls.sidecar_type(Path(value)), 9),
                Path(value).name.casefold(),
            ),
        )

    @staticmethod
    def _path_key(path: str | Path) -> str:
        import os
        return os.path.normcase(os.path.abspath(str(path)))

    @classmethod
    def _paths_equivalent(cls, source: Path, dest: Path) -> bool:
        try:
            if source.is_file() and dest.is_file():
                if source.stat().st_size != dest.stat().st_size:
                    return False
                return filecmp.cmp(source, dest, shallow=False)
            if source.is_dir() and dest.is_dir():
                source_files = {
                    p.relative_to(source): p
                    for p in source.rglob("*")
                    if p.is_file()
                }
                dest_files = {
                    p.relative_to(dest): p
                    for p in dest.rglob("*")
                    if p.is_file()
                }
                if source_files.keys() != dest_files.keys():
                    return False
                for rel, source_file in source_files.items():
                    dest_file = dest_files[rel]
                    if source_file.stat().st_size != dest_file.stat().st_size:
                        return False
                    if not filecmp.cmp(source_file, dest_file, shallow=False):
                        return False
                return True
        except OSError:
            return False
        return False

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

    def sidecar_dest_name(
        self,
        sidecar_p: Path,
        target_dir: str,
        *,
        video_path: str | None = None,
        dest_video_path: str | None = None,
    ) -> str:
        # Film-NFOs may intentionally use the canonical Jellyfin name. This
        # rule takes precedence over stem rebasing.
        if sidecar_p.suffix.lower() == ".nfo" and self.is_film_target(target_dir):
            configured = str(self.nfo_movie_target_name or "").strip()
            if configured != "stem":
                return configured or "movie.nfo"

        return self._rebase_companion_name(
            sidecar_p.name,
            video_path=video_path,
            dest_video_path=dest_video_path,
        )

    @staticmethod
    def _rebase_companion_name(
        sidecar_name: str,
        *,
        video_path: str | None,
        dest_video_path: str | None,
    ) -> str:
        """Keep companion stems aligned with a conflict-renamed video.

        Example: ``Film.mkv`` -> ``Film_01.mkv`` also maps
        ``Film.de.srt``/``Film.trickplay``/``Film.nfo`` to the ``Film_01`` stem.
        Unrelated sidecars (for example ``movie.nfo``) are left untouched.
        """
        if not video_path or not dest_video_path:
            return sidecar_name
        source_stem = Path(video_path).stem
        dest_stem = Path(dest_video_path).stem
        if not source_stem or not dest_stem or source_stem.casefold() == dest_stem.casefold():
            return sidecar_name
        if sidecar_name.casefold() == source_stem.casefold():
            return dest_stem
        prefix = f"{source_stem}."
        if sidecar_name[: len(prefix)].casefold() == prefix.casefold():
            return f"{dest_stem}{sidecar_name[len(source_stem):]}"
        return sidecar_name

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
