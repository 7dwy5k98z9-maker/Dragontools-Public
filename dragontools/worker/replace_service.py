# -*- coding: utf-8 -*-
from __future__ import annotations

import os
from pathlib import Path
from typing import Callable

from ..core.output_replace import commit_staged_output
from .output_size_policy import validate_output_size_policy


class ReplaceService:
    """Kapselt Overwrite-/Replace-Logik inkl. Sicherheitsprüfungen."""

    def __init__(self, *, overwrite_original: bool, log: Callable[[str, str], None], journal_root: str | Path | None = None) -> None:
        self._overwrite_original = overwrite_original
        self._log = log
        self._blocked_move_inputs: set[str] = set()
        self._archiviert: int = 0
        self._last_blocked_input: str | None = None
        self._last_preserved_path: str | None = None
        self._last_block_reason: str = ""
        self._journal_root = journal_root
        self._cleanup_pending_inputs: set[str] = set()
        self._last_cleanup_message: str = ""

    @property
    def blocked_move_inputs(self) -> set[str]:
        return self._blocked_move_inputs

    @property
    def archiviert(self) -> int:
        """Anzahl der Dateien, die aufgrund der Größenregel in Archiv/ abgelegt wurden."""
        return self._archiviert

    @property
    def last_blocked_input(self) -> str | None:
        return self._last_blocked_input

    @property
    def last_preserved_path(self) -> str | None:
        return self._last_preserved_path

    @property
    def last_block_reason(self) -> str:
        return self._last_block_reason

    def was_blocked(self, input_path: str) -> bool:
        return self._last_blocked_input == input_path

    @property
    def cleanup_pending_inputs(self) -> set[str]:
        return self._cleanup_pending_inputs

    @property
    def last_cleanup_message(self) -> str:
        return self._last_cleanup_message

    def cleanup_pending(self, input_path: str) -> bool:
        return input_path in self._cleanup_pending_inputs

    def replace(self, *, input_path: str, output_path: str | None, container: str) -> str:
        if not output_path:
            raise RuntimeError("Kein Ausgabepfad für Replace-Schritt vorhanden.")

        self._blocked_move_inputs.discard(input_path)
        self._last_blocked_input = None
        self._last_preserved_path = None
        self._last_block_reason = ""
        self._cleanup_pending_inputs.discard(input_path)
        self._last_cleanup_message = ""

        allowed, preserved_path = validate_output_size_policy(
            input_path=input_path,
            output_path=output_path,
            logger=self._log,
        )
        if not allowed:
            self._blocked_move_inputs.add(input_path)
            self._last_blocked_input = input_path
            self._last_preserved_path = str(preserved_path) if preserved_path is not None else None
            self._last_block_reason = self._infer_size_block_reason(
                input_path=input_path,
                preserved_path=str(preserved_path) if preserved_path is not None else output_path,
            )
            if preserved_path is not None:
                self._archiviert += 1
            return str(preserved_path or output_path)

        if not self._overwrite_original:
            return output_path

        final_path = Path(input_path).with_suffix(f".{container}")
        out_path = Path(output_path)
        if not out_path.exists() or out_path.stat().st_size < 1024:
            raise RuntimeError(
                f"📝 Temporäre Ausgabedatei fehlt oder ist unplausibel klein: {out_path.name}"
            )

        input_path_obj = Path(input_path)
        final_resolved = final_path.resolve()
        if final_path.exists():
            input_resolved = input_path_obj.resolve()
            out_resolved = out_path.resolve()
            if final_resolved != input_resolved and final_resolved != out_resolved:
                raise RuntimeError(
                    f"Zieldatei existiert bereits und wird nicht überschrieben: {final_path.name}"
                )

        if final_resolved == input_path_obj.resolve():
            return self._replace_same_path_with_rollback(
                input_path=input_path_obj,
                output_path=out_path,
                final_path=final_path,
            )

        result = commit_staged_output(
            source=input_path_obj,
            staging=out_path,
            destination=final_path,
            log=self._log,
            journal_root=self._journal_root,
            min_size=1024,
            remove_source=lambda path: os.remove(path),
        )
        if result.cleanup_pending:
            self._cleanup_pending_inputs.add(input_path)
            self._last_cleanup_message = result.cleanup_message
        return str(result.destination)

    @staticmethod
    def _infer_size_block_reason(*, input_path: str, preserved_path: str) -> str:
        try:
            input_size = Path(input_path).stat().st_size
            output_size = Path(preserved_path).stat().st_size
            if input_size > 0 and output_size > input_size:
                return "Ausgabedatei ist größer als erlaubt; Original wurde nicht ersetzt."
            if input_size > 0 and output_size < input_size:
                return "Ausgabedatei ist kleiner als erlaubt; Original wurde nicht ersetzt."
        except (OSError, TypeError, ValueError):
            pass
        return "Ausgabedatei verletzt die Größenregel; Original wurde nicht ersetzt."

    def _replace_same_path_with_rollback(
        self,
        *,
        input_path: Path,
        output_path: Path,
        final_path: Path,
    ) -> str:
        result = commit_staged_output(
            source=input_path,
            staging=output_path,
            destination=final_path,
            log=self._log,
            journal_root=self._journal_root,
            min_size=1024,
            remove_source=lambda path: os.remove(path),
        )
        if result.cleanup_pending:
            self._cleanup_pending_inputs.add(str(input_path))
            self._last_cleanup_message = result.cleanup_message
        return str(result.destination)
