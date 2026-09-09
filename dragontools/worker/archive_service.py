# -*- coding: utf-8 -*-
"""
dragontools/worker/archive_service.py

Zentrale Archivierungsfunktion für Quelldateien, bevor Metadaten
(HDR10+/DV) bei codecbedingter Inkompatibilitaet verloren gehen.

Regeln:
  - Ordner "Archiv" wird direkt neben der Quelldatei angelegt.
  - Vorhandene Dateien werden NICHT überschrieben.
  - Bei Namenskonflikt: eindeutiger Name (_001, _002, ...).
  - Größe der Kopie wird gegen Quelle geprüft.
  - Bei Fehler: RuntimeError (Verarbeitung muss abgebrochen werden).
  - Quelldatei wird NIEMALS gelöscht.
"""
from __future__ import annotations

import shutil
from pathlib import Path
from typing import Callable


class ArchiveService:
    """Sichert Quelldateien in einen 'Archiv'-Unterordner.

    Wird vor verlustbehafteter Konvertierung (z. B. H264+HDR10+ oder nicht freigegebene AV1-Metadatenkombinationen)
    aufgerufen. Wirft RuntimeError wenn Archivierung fehlschlaegt, damit
    der Workflow sauber abbricht anstatt still fortzufahren.
    """

    _ARCHIVE_DIR_NAME = "Archiv"
    _MAX_RENAME_ATTEMPTS = 999

    def __init__(self, log: Callable[[str, str], None]) -> None:
        self._log = log

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def archive_original(self, input_path: str, reason: str) -> Path:
        """Kopiert *input_path* nach <Elternordner>/Archiv/<Dateiname>.

        Args:
            input_path: Absoluter Pfad der Quelldatei.
            reason:     Menschenlesbare Begründung für das Logging.

        Returns:
            Pfad der erzeugten Archivkopie.

        Raises:
            RuntimeError: Bei jedem Fehler, der eine sichere Archivierung
                          verhindert. Der Aufrufer muss die Verarbeitung dann
                          abbrechen.
        """
        src = Path(input_path)
        self._assert_source_exists(src)

        archive_dir = self._ensure_archive_dir(src)
        dest = self._unique_dest(archive_dir, src)

        self._log(
            f"📦 Archivierung gestartet: '{src.name}' → '{archive_dir.name}/{dest.name}' "
            f"(Grund: {reason})",
            "info",
        )

        self._copy_file(src, dest)
        self._verify_size(src, dest)

        self._log(
            f"✅ Archivierung erfolgreich: '{dest.name}' "
            f"({dest.stat().st_size:,} Bytes) in '{archive_dir}'",
            "info",
        )
        return dest

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _assert_source_exists(self, src: Path) -> None:
        if not src.exists():
            msg = (
                f"Archivierung fehlgeschlagen: Quelldatei nicht gefunden: {src.name}"
            )
            self._log(f"❌ {msg}", "error")
            raise RuntimeError(msg)

    def _ensure_archive_dir(self, src: Path) -> Path:
        archive_dir = src.parent / self._ARCHIVE_DIR_NAME
        try:
            archive_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            msg = (
                f"Archivierung fehlgeschlagen: Ordner '{archive_dir}' "
                f"konnte nicht angelegt werden: {exc}"
            )
            self._log(f"❌ {msg}", "error")
            raise RuntimeError(msg) from exc
        return archive_dir

    @classmethod
    def _unique_dest(cls, archive_dir: Path, src: Path) -> Path:
        """Gibt einen freien Zielpfad zurück.

        Bei Namenskonflikt wird _001, _002, ... angefuegt.
        """
        candidate = archive_dir / src.name
        if not candidate.exists():
            return candidate
        stem = src.stem
        suffix = src.suffix
        for i in range(1, cls._MAX_RENAME_ATTEMPTS + 1):
            candidate = archive_dir / f"{stem}_{i:03d}{suffix}"
            if not candidate.exists():
                return candidate
        raise RuntimeError(
            f"Archivierung fehlgeschlagen: Kein freier Dateiname nach "
            f"{cls._MAX_RENAME_ATTEMPTS} Versuchen für '{src.name}'"
        )

    def _copy_file(self, src: Path, dest: Path) -> None:
        try:
            shutil.copy2(str(src), str(dest))
        except OSError as exc:
            # Fehlgeschlagene Teilkopie aufraumen
            try:
                dest.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                self._log(
                    f"⚠️ Unvollständige Archivkopie konnte nicht entfernt werden: {dest.name} – {cleanup_exc}",
                    "warn",
                )
            msg = (
                f"Archivierung fehlgeschlagen: Kopieren schlug fehl "
                f"({src.name} → {dest.name}): {exc}"
            )
            self._log(f"❌ {msg}", "error")
            raise RuntimeError(msg) from exc

    def _verify_size(self, src: Path, dest: Path) -> None:
        src_size = src.stat().st_size
        dest_size = dest.stat().st_size if dest.exists() else -1
        if dest_size != src_size:
            try:
                dest.unlink(missing_ok=True)
            except OSError as cleanup_exc:
                self._log(
                    f"⚠️ Fehlerhafte Archivkopie konnte nicht entfernt werden: {dest.name} – {cleanup_exc}",
                    "warn",
                )
            msg = (
                f"Archivierung fehlgeschlagen: Größe stimmt nicht überein "
                f"(Quelle={src_size:,} B, Kopie={dest_size:,} B): {dest.name}"
            )
            self._log(f"❌ {msg}", "error")
            raise RuntimeError(msg)
