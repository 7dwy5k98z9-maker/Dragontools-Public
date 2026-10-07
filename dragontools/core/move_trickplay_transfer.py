"""Transactional transfer of trickplay directories; sidecar naming stays in the facade."""
from pathlib import Path
import errno
import os
import shutil
from .move_file_service import new_move_result
from .move_conflicts import same_path
from .move_transaction import PathSwapTransaction, PathTransactionRollbackError, publish_staged_no_replace
from .transaction_identity import path_receipt, receipt_matches

def move_trickplay_path(src_p: Path, dst_p: Path, *, mode, log, record_companion,
        remove_verified_source, overwrite_backup_path, trickplay_backup_path) -> tuple[bool, dict]:
    result = new_move_result(str(src_p), str(dst_p.parent), dest_name=dst_p.name)
    transaction: PathSwapTransaction | None = None
    try:
        source_receipt = path_receipt(src_p)
        dst_p.parent.mkdir(parents=True, exist_ok=True)
        result["target_dir"] = str(dst_p.parent)
        result["dest_path"] = str(dst_p)
        if dst_p.exists() and same_path(src_p, dst_p):
            result["ok"] = True
            log(f"ℹ️ Trickplay liegt bereits im Zielordner: {dst_p.name}", "info")
            return True, result

        if not dst_p.exists():
            record_companion(src_p, dst_p, source_receipt, destination_receipt=source_receipt)
            try:
                publish_staged_no_replace(src_p, dst_p)
            except OSError as exc:
                if exc.errno != errno.EXDEV and getattr(exc, "winerror", None) != 17:
                    raise
                transaction = PathSwapTransaction(
                    src_p,
                    dst_p,
                    overwrite_backup_path(dst_p),
                    replace_existing_destination=False,
                )
                transaction.stage()
                if not receipt_matches(src_p, source_receipt):
                    raise OSError('Trickplay-Quelle wurde nach der Kopierprüfung verändert.')
                transaction.commit()
                record_companion(src_p, dst_p, source_receipt)
                if not remove_verified_source(src_p, dst_p, source_receipt):
                    result["cleanup_pending"] = True
                    return False, result
            result["ok"] = True
            return True, result

        result["conflict"] = True
        result["conflict_paths"] = [str(dst_p)]
        if mode == "skip":
            result["skipped_conflict"] = True
            log(f"  🧩 Trickplay im Ziel vorhanden, wird behalten: {dst_p.name}", "info")
            result['source_retained'] = True
            result["ok"] = True
            return True, result

        if mode not in {"backup", "overwrite"}:
            raise ValueError(f"Unbekannter Trickplay-Konfliktmodus: {mode}")

        backup_mode = mode == "backup"
        backup_p = trickplay_backup_path(dst_p) if backup_mode else overwrite_backup_path(dst_p)
        transaction = PathSwapTransaction(src_p, dst_p, backup_p)
        transaction.stage()
        if not receipt_matches(src_p, source_receipt):
            raise OSError('Trickplay-Quelle wurde nach der Kopierprüfung verändert.')
        transaction.commit()
        record_companion(src_p, dst_p, source_receipt)
        cleanup_ok = remove_verified_source(src_p, dst_p, source_receipt)
        result["ok"] = bool(cleanup_ok)
        result["cleanup_pending"] = not cleanup_ok
        result["dest_path"] = str(dst_p)

        if backup_mode:
            result["backed_up_existing"] = True
            result["backed_up_existing_count"] = 1
            log(f"  🧩 Vorhandene Trickplaybilder gesichert: {backup_p.name}", "info")
        else:
            result["replaced_existing"] = True
            result["replaced_existing_count"] = 1
            try:
                if cleanup_ok:
                    transaction.discard_backup()
            except (OSError, shutil.Error) as cleanup_exc:
                log(
                    f"⚠️ Altes Trickplay-Backup konnte nach erfolgreichem Commit nicht entfernt werden: {cleanup_exc}",
                    "warn",
                )
            log(f"  🧩 Vorhandene Trickplaybilder transaktional ersetzt: {dst_p.name}", "info")
        if not cleanup_ok:
            log(
                f"⚠️ Trickplay-Ziel ist installiert, aber die Quellstruktur konnte nicht entfernt werden: {src_p.name}",
                "warn",
            )
        return bool(cleanup_ok), result
    except (OSError, shutil.Error, PathTransactionRollbackError, ValueError, RuntimeError) as exc:
        log(f"❌ Fehler beim Verschieben der Trickplaybilder: {exc}", "error")
        if transaction is not None:
            transaction.cleanup_staging(best_effort=True)
            if transaction.backup_created and not dst_p.exists():
                try:
                    transaction.rollback()
                    log(f"↩️ Vorhandene Trickplaybilder wiederhergestellt: {dst_p.name}", "warn")
                except (OSError, shutil.Error) as rollback_exc:
                    log(
                        "❌ Trickplay-Rollback unvollständig; Backup bleibt erhalten: "
                        f"{transaction.backup_path} – {rollback_exc}",
                        "error",
                    )
        return False, result
