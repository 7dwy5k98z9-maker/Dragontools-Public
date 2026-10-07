# -*- coding: utf-8 -*-
"""Transaktionale Finalisierung erzeugter Sidecar-Dateien.

Die Pipeline erzeugt Untertitel-Sidecars bewusst neben einem temporaeren
Videopfad. Erst am Commit-Punkt werden sie auf den finalen Video-Stem
verschoben. Bereits vorhandene Sidecars werden dabei *nicht* still geloescht:
sie bleiben unter einem eindeutigen ``.dragontools_backup``-Namen erhalten.

Die Transaktion ist innerhalb eines laufenden Prozesses rollback-faehig. Eine
dauerhafte Crash-Recovery (Stromausfall/Hard-Kill) gehoert zum separaten
Journal-/Recovery-Block und wird hier absichtlich nicht vorweggenommen.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from .move_transaction import publish_staged_no_replace
from .transaction_identity import path_receipt, receipt_matches


class SidecarCommitError(OSError):
    """Sidecar-Commit oder dessen Rollback ist fehlgeschlagen."""


@dataclass
class _CommittedSidecar:
    source: Path
    destination: Path
    backup: Path | None = None
    noop: bool = False
    destination_receipt: dict | None = None
    backup_receipt: dict | None = None


class SidecarCommitTransaction:
    """Verschiebt mehrere Sidecars gemeinsam und rollback-faehig.

    Bereits vorhandene Ziele werden vor dem Commit auf einen eindeutigen
    Backup-Pfad umbenannt. Nach erfolgreichem Commit bleiben diese Backups
    absichtlich erhalten, damit ein vorhandenes Benutzer-Sidecar niemals
    still verloren geht.
    """

    def __init__(
        self,
        sidecar_paths: list[str] | tuple[str, ...],
        *,
        source_base: str | Path,
        destination_base: str | Path,
    ) -> None:
        self._sources = [Path(p) for p in sidecar_paths]
        # source_base/destination_base sind bereits Video-Stems. Ein erneutes
        # Path.with_suffix("") waere bei Namen wie "Film.2026" oder unseren
        # Temp-Stems ("Film.__mp4_remux_tmp__") destruktiv.
        self.source_base = Path(source_base)
        self.destination_base = Path(destination_base)
        self._records: list[_CommittedSidecar] = []
        self._planned_records: list[dict[str, str]] | None = None
        self._committed = False


    def prepare_records(self) -> list[dict[str, str]]:
        """Berechnet den vollstaendigen Commit-Plan ohne Dateisystemmutation."""
        if self._planned_records is not None:
            return [dict(row) for row in self._planned_records]
        rows: list[dict[str, str]] = []
        for source in self._sources:
            if not (source.exists() or source.is_symlink()):
                raise FileNotFoundError(f"Erzeugtes Sidecar fehlt: {source}")
            destination = self._destination_for(source)
            try:
                same_path = source.resolve() == destination.resolve()
            except OSError:
                same_path = source.absolute() == destination.absolute()
            backup = None
            if not same_path and (destination.exists() or destination.is_symlink()):
                backup = self._unique_backup_path(destination)
            rows.append({
                "source": str(source),
                "destination": str(destination),
                "backup": str(backup) if backup is not None else "",
                "noop": "1" if same_path else "0",
                'new_receipt': path_receipt(source),
                'old_receipt': path_receipt(destination) if backup is not None else None,
            })
        self._planned_records = rows
        return [dict(row) for row in rows]

    @property
    def backup_pairs(self) -> list[tuple[Path, Path]]:
        """Liefert ``(urspruengliches Ziel, Backup)`` fuer ersetzte Sidecars."""
        return [
            (record.destination, record.backup)
            for record in self._records
            if record.backup is not None
        ]

    @property
    def final_paths(self) -> list[str]:
        return [str(record.destination) for record in self._records]

    def commit(self) -> list[str]:
        if self._committed:
            return self.final_paths
        if self._records:
            raise SidecarCommitError('Sidecar-Rollback ist noch ausstehend; neuer Commit ist gesperrt.')

        try:
            for row in self.prepare_records():
                record = self._commit_one_prepared(row)
                self._records.append(record)
        except Exception as exc:
            try:
                self.rollback()
            except Exception as rollback_exc:
                raise SidecarCommitError(
                    "Sidecar-Commit fehlgeschlagen und Rollback war unvollstaendig: "
                    f"Commit={exc}; Rollback={rollback_exc}"
                ) from exc
            raise SidecarCommitError(f"Sidecar-Commit fehlgeschlagen: {exc}") from exc

        self._committed = True
        return self.final_paths

    def rollback(self) -> None:
        errors: list[str] = []
        pending: list[_CommittedSidecar] = []
        for record in reversed(self._records):
            if record.noop:
                continue
            try:
                # Neu erzeugtes Sidecar wieder an seinen Staging-Pfad legen.
                if record.destination.exists() or record.destination.is_symlink():
                    if not receipt_matches(record.destination, record.destination_receipt):
                        raise OSError('Sidecar-Ziel wurde nach Commit verändert; bleibt erhalten.')
                    if record.source.exists() or record.source.is_symlink():
                        raise FileExistsError(
                            f"Rollback-Quelle existiert bereits: {record.source}"
                        )
                    record.source.parent.mkdir(parents=True, exist_ok=True)
                    publish_staged_no_replace(record.destination, record.source)

                # Vorheriges Benutzer-Sidecar wieder auf den Originalnamen setzen.
                if record.backup is not None and (
                    record.backup.exists() or record.backup.is_symlink()
                ):
                    if record.destination.exists() or record.destination.is_symlink():
                        raise FileExistsError(
                            f"Rollback-Ziel ist belegt: {record.destination}"
                        )
                    if not receipt_matches(record.backup, record.backup_receipt):
                        raise OSError('Sidecar-Backup wurde nach Commit verändert; bleibt erhalten.')
                    publish_staged_no_replace(record.backup, record.destination)
            except Exception as exc:
                errors.append(f"{record.destination.name}: {exc}")
                pending.append(record)

        # Completed records must never inspect the restored old destination as
        # though it were still the new candidate on a retry or second cleanup.
        self._records = list(reversed(pending))
        self._committed = False
        if errors:
            raise SidecarCommitError("; ".join(errors))

    def _commit_one(self, source: Path) -> _CommittedSidecar:
        """Kompatibilitaetshelfer fuer direkte Einzelaufrufe."""
        destination = self._destination_for(source)
        backup = None
        if destination.exists() or destination.is_symlink():
            backup = self._unique_backup_path(destination)
        return self._commit_one_prepared({
            "source": str(source),
            "destination": str(destination),
            "backup": str(backup) if backup is not None else "",
            "noop": "0",
            'new_receipt': path_receipt(source),
            'old_receipt': path_receipt(destination) if backup is not None else None,
        })

    def _commit_one_prepared(self, row: dict[str, str]) -> _CommittedSidecar:
        source = Path(row["source"])
        destination = Path(row["destination"])
        backup_text = str(row.get("backup") or "")
        backup = Path(backup_text) if backup_text else None
        noop = str(row.get("noop") or "0") == "1"

        if not (source.exists() or source.is_symlink()):
            raise FileNotFoundError(f"Erzeugtes Sidecar fehlt: {source}")
        if not receipt_matches(source, row.get('new_receipt')):
            raise OSError('Sidecar-Staging wurde nach der Planung verändert.')
        destination.parent.mkdir(parents=True, exist_ok=True)
        if noop:
            return _CommittedSidecar(source, destination, noop=True)

        if backup is not None:
            if backup.exists() or backup.is_symlink():
                raise FileExistsError(f"Geplanter Sidecar-Backup-Pfad ist bereits belegt: {backup}")
            if not (destination.exists() or destination.is_symlink()):
                raise FileNotFoundError(f"Zu sicherndes Sidecar fehlt vor Commit: {destination}")
            if not receipt_matches(destination, row.get('old_receipt')):
                raise OSError('Sidecar-Altbestand wurde nach der Planung verändert.')
            publish_staged_no_replace(destination, backup)
            backup_receipt = path_receipt(backup)
        elif destination.exists() or destination.is_symlink():
            raise FileExistsError(
                f"Sidecar-Ziel wurde nach der Planung unerwartet belegt: {destination}"
            )

        try:
            publish_staged_no_replace(source, destination)
        except Exception:
            if backup is not None and (backup.exists() or backup.is_symlink()):
                if destination.exists() or destination.is_symlink():
                    raise
                if not receipt_matches(backup, backup_receipt):
                    raise OSError('Sidecar-Backup wurde verändert; bleibt erhalten.')
                publish_staged_no_replace(backup, destination)
            raise
        return _CommittedSidecar(source, destination, backup=backup,
            destination_receipt=path_receipt(destination),
            backup_receipt=path_receipt(backup) if backup is not None else None)

    def _destination_for(self, source: Path) -> Path:
        source_name = source.name
        base_name = self.source_base.name
        if not source_name.startswith(base_name + '.'):
            raise ValueError(
                "Sidecar-Name passt nicht zum erwarteten Quell-Stem: "
                f"{source_name} / {base_name}"
            )
        tail = source_name[len(base_name):]
        if not tail:
            raise ValueError(f"Sidecar besitzt keinen Suffix-Anteil: {source_name}")
        return self.destination_base.parent / f"{self.destination_base.name}{tail}"

    @staticmethod
    def _unique_backup_path(destination: Path) -> Path:
        base = destination.with_name(f"{destination.name}.dragontools_backup")
        if not base.exists() and not base.is_symlink():
            return base
        counter = 1
        while True:
            candidate = destination.with_name(
                f"{destination.name}.dragontools_backup_{counter}"
            )
            if not candidate.exists() and not candidate.is_symlink():
                return candidate
            counter += 1
