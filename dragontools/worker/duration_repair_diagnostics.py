"""Receipts for rejected repair copies; remove them only after a successful run."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.path_safety import is_safe_subpath, safe_unlink
from ..core.transaction_identity import stat_identity


@dataclass(frozen=True, slots=True)
class RepairDiagnosticReceipt:
    path: str
    root: str
    identity: tuple


class RejectedRepairCandidates:
    def __init__(self):
        self._receipts = []

    def clear(self):
        self._receipts.clear()

    @property
    def receipts(self):
        return tuple(self._receipts)

    def record(self, target):
        path = Path(target)
        try:
            if path.is_symlink() or path.parent.name != "Timestamp_Reparatur":
                return
            path = path.resolve()
            self._receipts.append(RepairDiagnosticReceipt(
                str(path), str(path.parent), tuple(stat_identity(path))
            ))
        except OSError:
            # Without ownership evidence the diagnostic copy must be kept.
            return


def cleanup_successful_repair_diagnostics(ctx, log):
    if not getattr(ctx, "success", False) or not getattr(getattr(ctx, "verify_result", None), "ok", False):
        return
    removed = 0
    for receipt in getattr(ctx, "duration_repair_rejected_candidates", ()):
        if not isinstance(receipt, RepairDiagnosticReceipt):
            continue
        path, root = Path(receipt.path), Path(receipt.root)
        try:
            if root.resolve() != root or path.is_symlink() or not is_safe_subpath(root, path):
                continue
            if tuple(stat_identity(path)) != receipt.identity:
                continue
            if safe_unlink(root, path):
                removed += 1
        except OSError:
            continue
    if removed:
        log(f"ℹ️ Erfolgreiche Verarbeitung: {removed} verworfene Timestamp-Reparaturkopie(n) entfernt.", "info")
