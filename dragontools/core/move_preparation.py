# -*- coding: utf-8 -*-
"""Non-destructive move planning and companion-aware commit resolution."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable, Iterable
from .transaction_identity import path_receipt, receipt_matches, validate_destination_name
from .move_result import new_move_result
from .movie_replacement_preparation import (validate_movie_replacement,approve_movie_replacement,
    movie_commit_artifacts)

from .move_conflicts import (
    find_episode_identity_conflicts,
    find_episode_replacement_artifacts,
    find_target_conflicts,
    format_conflict_names,
    resolve_rename_path,
    same_path,
)


class MovePreparationService:
    """Resolve final video names before companions are exposed to Jellyfin."""

    def __init__(
        self,
        *,
        conflict_mode: str,
        log: Callable[[str, str], None],
        journal_set_destination: Callable[[str | Path, Path], None],
        allow_episode_replacement: Callable[[dict, Path, list[Path]], bool],
        describe_episode_replacement: Callable[[dict, Path, list[Path], list[Path]], None],
    ) -> None:
        self.conflict_mode = conflict_mode
        self._log = log
        self._journal_set_destination = journal_set_destination
        self._allow_episode_replacement = allow_episode_replacement
        self._describe_episode_replacement = describe_episode_replacement

    def prepare(self, src, dst_dir, *, dest_name: str | None = None) -> dict:
        validate_destination_name(dest_name)
        result = new_move_result(src, dst_dir, dest_name=dest_name)
        dp = Path(dst_dir)
        dp.mkdir(parents=True, exist_ok=True)
        src_p = Path(src)
        dst_p = dp / (dest_name or src_p.name)
        result["target_dir"] = str(dp)
        result["dest_path"] = str(dst_p)
        self._journal_set_destination(src_p, dst_p)
        prepared = {
            "ready": True,
            "source_path": str(src_p),
            'source_receipt': path_receipt(src_p) if src_p.exists() else None,
            "target_dir": str(dp),
            "dest_path": str(dst_p),
            "result": result,
            "replacement_mode": None,
            "episode_replacement_preapproved": False,
            "renamed": False,
            "same_path": False,
        }
        if src_p.is_dir():
            return prepared
        if dst_p.exists() and same_path(src_p, dst_p):
            prepared["same_path"] = True
            return prepared

        conflicts = find_target_conflicts(dst_p, src_p)
        movie_error,movie_conflicts=validate_movie_replacement(src_p,dst_p,conflicts)
        if movie_error:
            prepared['ready']=False
            result['error']=movie_error
            return prepared
        prepared['approved_conflicts'] = {str(path): path_receipt(path) for path in conflicts}
        if not conflicts:
            return prepared
        result["conflict"] = True
        result["conflict_paths"] = [str(path) for path in conflicts]
        episode_conflicts = find_episode_identity_conflicts(dst_p, src_p)
        if episode_conflicts:
            if not self._allow_episode_replacement(result, dst_p, episode_conflicts):
                prepared["ready"] = False
                return prepared
            artifacts = find_episode_replacement_artifacts(dst_p, episode_conflicts)
            prepared['approved_artifacts'] = {str(path): path_receipt(path) for path in artifacts}
            prepared["episode_replacement_preapproved"] = True
            prepared["replacement_mode"] = "delete_first"
            return prepared

        mode = self.conflict_mode
        if mode == "skip":
            result["skipped_conflict"] = True
            self._log(
                "⚠️ Ziel existiert bereits, übersprungen: " + format_conflict_names(conflicts),
                "warn",
            )
            prepared["ready"] = False
        elif mode in {"delete_first", "overwrite"}:
            prepared["replacement_mode"] = mode
            approve_movie_replacement(prepared,src_p,dst_p,movie_conflicts)
        elif mode == "rename":
            dst_p = resolve_rename_path(dst_p, src_p)
            result["renamed"] = True
            result["dest_path"] = str(dst_p)
            prepared["dest_path"] = str(dst_p)
            prepared["renamed"] = True
            self._journal_set_destination(src_p, dst_p)
            self._log(f"📝 Umbenennung: Zieldatei heißt jetzt {dst_p.name}", "info")
        else:
            result["error"] = f"Unbekannter Konfliktmodus: {mode}"
            prepared["ready"] = False
            self._log(f"❌ Unbekannter Konfliktmodus: {mode}", "error")
        return prepared

    @staticmethod
    def _path_keys(paths: Iterable[str | os.PathLike] | None) -> set[str]:
        return {
            os.path.normcase(os.path.abspath(os.fspath(path)))
            for path in (paths or [])
            if str(path or "").strip()
        }

    def resolve_commit(
        self,
        prepared: dict,
        *,
        src_p: Path,
        dst_p: Path,
        protected_paths: Iterable[str | os.PathLike] | None = None,
    ) -> dict:
        approved = prepared.get('approved_conflicts', {})
        current = find_target_conflicts(dst_p, src_p)
        if any(not receipt_matches(path, approved.get(str(path))) for path in current):
            self._invalidate(prepared, [str(path) for path in current],
                'Vorbereitetes Move-Ziel hat sich geändert; Altbestand bleibt erhalten.')
            return {'ok': False, 'transaction_conflicts': [], 'replacement_mode': None}
        if bool(prepared.get("renamed")):
            late_conflicts = find_target_conflicts(dst_p, src_p)
            if late_conflicts:
                self._invalidate(
                    prepared,
                    [str(path) for path in late_conflicts],
                    "⚠️ Vorbereitetes Move-Ziel wurde zwischenzeitlich belegt; Datei wird nicht unter einem anderen Namen installiert.",
                )
                return {"ok": False, "transaction_conflicts": [], "replacement_mode": None}
            return {"ok": True, "transaction_conflicts": [], "replacement_mode": None}

        conflicts = find_target_conflicts(dst_p, src_p)
        episode_conflicts = find_episode_identity_conflicts(dst_p, src_p)
        if episode_conflicts and not bool(prepared.get("episode_replacement_preapproved")):
            self._invalidate(
                prepared,
                [str(path) for path in conflicts],
                "⚠️ Nach der Move-Vorbereitung ist ein neuer SxxExx-Konflikt entstanden; der Lauf wird zur sicheren Wiederholung abgebrochen.",
            )
            return {"ok": False, "transaction_conflicts": [], "replacement_mode": None}

        replacement_mode = prepared.get("replacement_mode")
        transaction_conflicts = list(conflicts)
        try:
            transaction_conflicts.extend(movie_commit_artifacts(prepared,src_p,dst_p,protected_paths))
        except ValueError as exc:
            self._invalidate(prepared,[str(p) for p in conflicts],str(exc))
            return {'ok':False,'transaction_conflicts':[],'replacement_mode':None}
        if episode_conflicts:
            replacement_mode = "delete_first"
            protected = self._path_keys(protected_paths)
            artifacts = [
                path
                for path in find_episode_replacement_artifacts(dst_p, episode_conflicts)
                if os.path.normcase(os.path.abspath(str(path))) not in protected
            ]
            approved_artifacts = prepared.get('approved_artifacts', {})
            if any(not receipt_matches(path, approved_artifacts.get(str(path))) for path in artifacts):
                self._invalidate(prepared, [str(path) for path in artifacts],
                    'Companion-Altbestand hat sich nach der Bestätigung geändert.')
                return {'ok': False, 'transaction_conflicts': [], 'replacement_mode': None}
            result = prepared["result"]
            self._describe_episode_replacement(result, dst_p, episode_conflicts, artifacts)
            for artifact in artifacts:
                if not any(same_path(artifact, current) for current in transaction_conflicts):
                    transaction_conflicts.append(artifact)

        if conflicts and replacement_mode not in {"delete_first", "overwrite"}:
            self._invalidate(
                prepared,
                [str(path) for path in conflicts],
                "⚠️ Zielkonflikt hat sich nach der Move-Vorbereitung geändert; Datei wird nicht verschoben.",
            )
            return {"ok": False, "transaction_conflicts": [], "replacement_mode": None}
        return {
            "ok": True,
            "transaction_conflicts": transaction_conflicts,
            "replacement_mode": replacement_mode,
        }

    def _invalidate(self, prepared: dict, conflict_paths: list[str], message: str) -> None:
        result = prepared["result"]
        result["preparation_invalidated"] = True
        result["conflict_paths"] = conflict_paths
        self._log(message, "warn")
