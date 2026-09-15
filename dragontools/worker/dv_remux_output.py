# -*- coding: utf-8 -*-
"""Output path, validation and transactional replacement for DV remux."""
from __future__ import annotations

import traceback
from pathlib import Path

from ..core.output_replace import OutputCommitResult, commit_staged_output
from .output_size_policy import validate_output_size_policy
from .dv_remux_output_verifier import DVRemuxOutputVerifier
from .dv_output_install import DVOutputInstallResult


class DVOutputManager:
    def __init__(self, worker):
        self.worker = worker
        self._archiviert = 0

    @property
    def archiviert(self) -> int:
        return self._archiviert

    def build_output_path(self, input_path: str) -> str:
        w = self.worker
        source = Path(input_path)
        if w.overwrite_original:
            temp_dir = source.parent / "__temp_dv_remux__"
            temp_dir.mkdir(exist_ok=True)
            return str(temp_dir / f"{source.stem}.{w.container}")

        candidate = source.parent / f"{source.stem}_DV_Remux.{w.container}"
        counter = 1
        while candidate.exists():
            candidate = source.parent / f"{source.stem}_DV_Remux_{counter}.{w.container}"
            counter += 1
        return str(candidate)

    def verify_output(self, *, output_path: str, media_info, expected_duration_ms: int | None, expected_contract=None) -> bool:
        verifier = DVRemuxOutputVerifier(tools=self.worker.tools)
        verification = verifier.verify(
            output_path=output_path,
            container=str(getattr(self.worker, "container", "mp4") or "mp4"),
            expected_duration_ms=expected_duration_ms,
            source_has_audio=bool(getattr(media_info, "audio_streams", None)),
            expected_contract=expected_contract,
        )
        if verification.ok:
            self.worker.log("✅ DV-Remux-Ausgabe vor dem Commit verifiziert.", "info")
            return True
        for message in verification.messages:
            self.worker.log(f"❌ DV-Remux-Validierung: {message}", "error")
        return False

    def replace_output_if_needed(self, input_path: str, output_path: str) -> DVOutputInstallResult:
        w = self.worker
        allowed, preserved_path = validate_output_size_policy(
            input_path=input_path,
            output_path=output_path,
            logger=w._log,
        )
        if not allowed:
            self._handle_rejected_output(input_path, output_path, preserved_path)
            return DVOutputInstallResult(
                False,
                str(preserved_path or output_path),
                preserved=preserved_path is not None,
            )

        if not w.overwrite_original:
            return DVOutputInstallResult(True, output_path, committed=True)

        final_path = Path(input_path).with_suffix(f".{w.container}")
        try:
            result = self._commit_overwrite(input_path, output_path, final_path)
            return DVOutputInstallResult(
                True,
                str(result.destination),
                committed=True,
                cleanup_pending=bool(result.cleanup_pending),
                cleanup_message=str(result.cleanup_message or ""),
                backup_path=str(result.backup_path) if result.backup_path is not None else None,
            )
        except Exception as exc:
            w.log(f"Ersetzen fehlgeschlagen: {exc}", "error")
            w.log(traceback.format_exc(), "error")
            return DVOutputInstallResult(False, output_path)
        finally:
            self.cleanup_temp_dir(input_path)

    def _handle_rejected_output(self, input_path: str, output_path: str, preserved_path: Path | None) -> None:
        w = self.worker
        if preserved_path is not None:
            self._archiviert += 1
            w.log(
                f"📦 DV-Ausgabe wegen Größenregel in Archiv/ abgelegt: {preserved_path.name}",
                "warn",
            )
        else:
            w.log(
                "⚠️ DV-Ausgabe wegen Größenregel verworfen (Archivierung fehlgeschlagen).",
                "warn",
            )
        self.cleanup_temp_dir(input_path)

    def _commit_overwrite(self, input_path: str, output_path: str, final_path: Path) -> OutputCommitResult:
        w = self.worker
        staging = Path(output_path)
        if not staging.exists() or staging.stat().st_size < 1024:
            raise RuntimeError(
                f"Temporäre DV-Ausgabedatei fehlt oder unplausibel klein: {staging.name}"
            )

        source = Path(input_path)
        if final_path.exists():
            final_resolved = final_path.resolve()
            if final_resolved not in {source.resolve(), staging.resolve()}:
                raise RuntimeError(
                    f"Zieldatei existiert bereits und wird nicht überschrieben: {final_path.name}"
                )

        return commit_staged_output(
            source=source,
            staging=staging,
            destination=final_path,
            log=w.log,
            min_size=1024,
        )

    def cleanup_temp_dir(self, input_path: str) -> None:
        temp_dir = Path(input_path).parent / "__temp_dv_remux__"
        try:
            temp_dir.rmdir()
        except FileNotFoundError:
            return
        except OSError as exc:
            if temp_dir.exists():
                self.worker.log(
                    f"Temporärer DV-Remux-Ordner konnte nicht entfernt werden: "
                    f"{temp_dir.name} - {exc}",
                    "warn",
                )

    def cleanup_incomplete(self, input_path: str, output_path: str | None) -> None:
        """Delete only known staging paths; committed/archived outputs are protected."""
        if output_path:
            candidate = Path(output_path)
            source = Path(input_path)
            safe_to_delete = False
            try:
                if bool(getattr(self.worker, "overwrite_original", False)):
                    safe_to_delete = candidate.resolve().parent == (
                        source.parent / "__temp_dv_remux__"
                    ).resolve()
                else:
                    safe_to_delete = (
                        candidate.resolve().parent == source.parent.resolve()
                        and candidate.name.startswith(f"{source.stem}_DV_Remux")
                    )
            except OSError:
                safe_to_delete = False
            if candidate.exists() and safe_to_delete:
                try:
                    candidate.unlink()
                except OSError as exc:
                    self.worker.log(
                        f"Unvollständige DV-Ausgabedatei konnte nicht gelöscht werden: "
                        f"{candidate.name} - {exc}",
                        "warn",
                    )
            elif candidate.exists() and not safe_to_delete:
                self.worker.log(
                    f"DV-Cleanup schützt bereits installierte/archivierte Ausgabe: {candidate.name}",
                    "warn",
                )
        self.cleanup_temp_dir(input_path)


__all__ = ["DVOutputInstallResult", "DVOutputManager"]
