# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..core.path_safety import is_safe_subpath, safe_unlink
from .output_path_service import release_output_path_reservation


class CleanupService:
    """Kapselt Burn-in- und Overwrite-Cleanup nach einem Workflow-Lauf."""

    def __init__(
        self,
        *,
        overwrite_original: bool,
        temp_overwrite_dir,
        log: Callable[[str, str], None],
    ) -> None:
        self._overwrite_original = overwrite_original
        self._temp_overwrite_dir = temp_overwrite_dir
        self._log = log

    def cleanup_temp_artifacts(
        self,
        *,
        burn_sub_tmp: str | None,
        base_dir: Path | None,
        output_path: str | None,
        sidecar_paths: list[str] | None = None,
        keep_output: bool = False,
    ) -> None:
        try:
            if burn_sub_tmp:
                path = Path(burn_sub_tmp)
                if path.exists():
                    if not base_dir or not is_safe_subpath(base_dir, path):
                        self._log(f"⚠️ Unsicherer Löschpfad übersprungen: {path}", "warn")
                    elif not safe_unlink(base_dir, path):
                        self._log(
                            f"🔥 Temporäre Burn-In-Datei konnte nicht gelöscht werden: {path.name}",
                            "warn",
                        )

            out_path = Path(output_path) if output_path else None

            if not self._overwrite_original:
                if not keep_output and out_path and out_path.exists():
                    if not base_dir or not is_safe_subpath(base_dir, out_path):
                        self._log(f"⚠️ Unsicherer Löschpfad übersprungen: {out_path}", "warn")
                    elif not safe_unlink(base_dir, out_path):
                        self._log(
                            f"⚠️ Unvollständige Ausgabedatei konnte nicht gelöscht werden: "
                            f"{out_path.name}",
                            "warn",
                        )
                if not keep_output:
                    # Nur explizit fuer diesen Run registrierte Sidecars loeschen.
                    # Namensbasierte ``output_stem.*``-Suche ist im Benutzerverzeichnis
                    # nicht ownership-sicher und kann bereits vorhandene Dateien treffen.
                    self._cleanup_sidecars(base_dir, sidecar_paths)
                return

            if base_dir is None:
                return

            tmp_dir = self._temp_overwrite_dir(base_dir)
            tmp_out = out_path

            if keep_output and tmp_out and tmp_out.exists() and tmp_out.parent == tmp_dir:
                return

            if tmp_out and tmp_out.exists() and tmp_out.parent == tmp_dir:
                if not is_safe_subpath(base_dir, tmp_out):
                    self._log(f"⚠️ Unsicherer Löschpfad übersprungen: {tmp_out}", "warn")
                elif not safe_unlink(base_dir, tmp_out):
                    self._log(
                        f"📝 Temporäre Overwrite-Datei konnte nicht gelöscht werden: {tmp_out.name}",
                        "warn",
                    )

            if not keep_output:
                self._cleanup_sidecars(base_dir, sidecar_paths)

        finally:
            release_output_path_reservation(output_path)

    def cleanup_empty_overwrite_dirs(self, base_dirs: list[Path] | set[Path] | tuple[Path, ...]) -> None:
        if not self._overwrite_original:
            return
        cleanup_empty_overwrite_dirs(
            base_dirs,
            temp_overwrite_dir=self._temp_overwrite_dir,
            log=self._log,
        )

    def _cleanup_sidecars(self, base_dir: Path | None, sidecar_paths: list[str] | None) -> None:
        if not base_dir:
            return
        for raw in sidecar_paths or []:
            path = Path(raw)
            if not path.exists() or path.is_dir():
                continue
            if not is_safe_subpath(base_dir, path):
                self._log(f"Warnung: Unsicherer Sidecar-Löschpfad übersprungen: {path}", "warn")
                continue
            if not safe_unlink(base_dir, path):
                self._log(
                    f"Warnung: Unvollständige Sidecar-Datei konnte nicht gelöscht werden: {path.name}",
                    "warn",
                )

def cleanup_empty_overwrite_dirs(
    base_dirs: list[Path] | set[Path] | tuple[Path, ...],
    *,
    temp_overwrite_dir,
    log: Callable[[str, str], None],
) -> None:
    seen: set[Path] = set()
    for raw_base in base_dirs or []:
        if raw_base is None:
            continue
        base_dir = Path(raw_base)
        try:
            base_key = base_dir.resolve()
        except Exception:
            base_key = base_dir
        if base_key in seen:
            continue
        seen.add(base_key)

        tmp_dir = temp_overwrite_dir(base_dir)
        if not tmp_dir.exists():
            continue
        if not is_safe_subpath(base_dir, tmp_dir):
            log(f"⚠️ Unsicherer Löschpfad übersprungen: {tmp_dir}", "warn")
            continue
        try:
            tmp_dir.rmdir()
        except OSError as exc:
            # Im Parallelbetrieb oder bei bewusst behaltenen Ausgaben darf der
            # Ordner noch Dateien enthalten. Dann bleibt er ohne Warnung stehen.
            try:
                if any(tmp_dir.iterdir()):
                    continue
            except Exception:
                pass
            log(
                f"📝 Temporärer Overwrite-Ordner konnte nicht gelöscht werden: {exc}",
                "warn",
            )
        except Exception as exc:
            log(
                f"📝 Temporärer Overwrite-Ordner konnte nicht gelöscht werden: {exc}",
                "warn",
            )
