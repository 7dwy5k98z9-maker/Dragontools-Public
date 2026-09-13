from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable

from ..core.move_transaction import PathSwapTransaction, PathTransactionRollbackError
from .trickplay_paths import unique_trickplay_backup_path

LogFn = Callable[[str], None]


def commit_missing_variant(
    *,
    partial_root: Path,
    partial_sprite_dir: Path,
    final_root: Path,
    final_sprite_dir: Path,
    info: LogFn,
    warn: LogFn,
) -> Path | None:
    if final_sprite_dir.exists():
        shutil.rmtree(partial_root, ignore_errors=True)
        info(f"Trickplay vorhanden, wird übernommen: {final_root.name}")
        return final_root
    try:
        final_sprite_dir.parent.mkdir(parents=True, exist_ok=True)
        partial_sprite_dir.rename(final_sprite_dir)
    except OSError as exc:
        warn(f"Trickplay-Variante konnte nicht committed werden: {exc}")
        return None
    shutil.rmtree(partial_root, ignore_errors=True)
    count = sum(1 for _ in final_sprite_dir.glob("*.jpg"))
    info(f"Trickplay ergänzt: {final_sprite_dir.parent.name} ({count} Kachelbild(er)).")
    return final_root


def commit_generated_root(
    *,
    partial_root: Path,
    final_root: Path,
    final_sprite_dir: Path,
    conflict_mode: str,
    info: LogFn,
    warn: LogFn,
) -> Path | None:
    final_root.parent.mkdir(parents=True, exist_ok=True)
    backup = unique_trickplay_backup_path(final_root)
    transaction = PathSwapTransaction(
        source=partial_root,
        destination=final_root,
        backup_path=backup,
        staging_path=partial_root,
    )
    try:
        transaction.commit()
    except PathTransactionRollbackError as exc:
        warn(
            "Trickplay-Commit fehlgeschlagen und automatisches Rollback war unvollständig. "
            f"Altbestand-Backup bleibt erhalten: {exc.backup_path}"
        )
        return None
    except (OSError, shutil.Error, RuntimeError) as exc:
        warn(
            "Trickplay-Commit fehlgeschlagen; vorhandener Altbestand wurde wiederhergestellt: "
            f"{exc}"
        )
        return None

    if transaction.backup_created:
        _finalize_backup(transaction, backup, conflict_mode, info, warn)

    count = sum(1 for _ in final_sprite_dir.glob("*.jpg"))
    info(f"Trickplay erstellt: {final_root.name} ({count} Kachelbild(er)).")
    return final_root


def _finalize_backup(
    transaction: PathSwapTransaction,
    backup: Path,
    conflict_mode: str,
    info: LogFn,
    warn: LogFn,
) -> None:
    if conflict_mode == "backup":
        info(f"Vorhandene Trickplaybilder gesichert: {backup.name}")
        return
    try:
        transaction.discard_backup()
    except (OSError, shutil.Error) as exc:
        warn(
            "Trickplay ersetzt; Altbestand-Backup konnte nicht entfernt werden "
            f"und bleibt unter {backup}: {exc}"
        )
