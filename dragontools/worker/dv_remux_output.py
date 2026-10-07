# -*- coding: utf-8 -*-
"""Output path, validation and transactional replacement for DV remux."""
from __future__ import annotations

import json
import traceback
import uuid
from functools import partial
from datetime import datetime
from pathlib import Path

from ..core.output_replace import OutputCommitResult, commit_staged_output
from .output_size_policy import validate_output_size_policy
from .dv_remux_output_verifier import DVRemuxOutputVerifier
from .log_dispatch import dispatch_log
from .dv_remux_output_paths import reserve_output_path, is_known_staging_path
from .dv_output_install import DVOutputInstallResult


class DVOutputManager:
    def __init__(self, worker):
        self.worker = worker
        self._log = partial(dispatch_log, worker.log)
        self._archiviert = 0
        self._owned_outputs: dict[str, Path] = {}

    @property
    def archiviert(self) -> int:
        return self._archiviert

    def build_output_path(self, input_path: str) -> str:
        w = self.worker
        source = Path(input_path)
        if w.overwrite_original:
            temp_dir = source.parent / "__temp_dv_remux__"
            temp_dir.mkdir(exist_ok=True)
            candidate = temp_dir / f"{source.stem}.{w.container}"
        else:
            candidate = source.parent / f"{source.stem}_DV_Remux.{w.container}"
        reserved = reserve_output_path(candidate)
        self._owned_outputs[str(source.resolve())] = reserved
        return str(reserved)

    def is_known_staging(self, input_path, output_path) -> bool:
        source = Path(input_path)
        return is_known_staging_path(source, Path(output_path),
            container=self.worker.container, overwrite=bool(self.worker.overwrite_original),
            owned=self._owned_outputs.get(str(source.resolve())))

    def verify_output(self, *, output_path: str, media_info, expected_duration_ms: int | None, expected_contract=None) -> bool:
        verifier = DVRemuxOutputVerifier(
            worker=self.worker,
            tools=self.worker.tools, process_runner=getattr(self.worker, "_process_runner", None)
        )
        verification = verifier.verify(
            output_path=output_path,
            container=str(getattr(self.worker, "container", "mp4") or "mp4"),
            expected_duration_ms=expected_duration_ms,
            source_has_audio=bool(getattr(media_info, "audio_streams", None)),
            expected_contract=expected_contract,
        )
        if verification.ok:
            self._log("✅ DV-Remux-Ausgabe vor dem Commit verifiziert.", "info")
            return True
        for message in verification.messages:
            self._log(f"❌ DV-Remux-Validierung: {message}", "error")
        return False

    def preserve_failed_output(
        self, input_path: str, output_path: str, *, reason: str = "DV-Remux-Verifikation fehlgeschlagen"
    ) -> str | None:
        """Move a valuable failed remux candidate into ``Archiv`` instead of deleting it.

        Only output paths produced by this manager are eligible.  The source is
        never touched and an archive collision cannot overwrite an existing file.
        """
        source = Path(input_path)
        candidate = Path(output_path)
        try:
            if not candidate.is_file() or candidate.stat().st_size <= 0:
                return None
            allowed = self.is_known_staging(input_path, output_path)
            if not allowed:
                self._log(
                    f"⚠️ DV-Recovery schützt unbekannten Kandidatenpfad vor Archivverschiebung: {candidate}",
                    "warn",
                )
                return None

            archive = source.parent / "Archiv"
            archive.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            token = uuid.uuid4().hex[:8]
            target = archive / f"{source.stem}__DV_REMUX_FAILED__{stamp}_{token}{candidate.suffix}"
            candidate.replace(target)
            status = target.with_suffix(target.suffix + ".recovery.json")
            try:
                status.write_text(
                    json.dumps(
                        {
                            "format": "DragonTools-DV-remux-recovery-v1",
                            "source": str(source),
                            "candidate": str(target),
                            "reason": str(reason or "DV-Remux fehlgeschlagen"),
                            "original_replaced": False,
                        },
                        ensure_ascii=False, indent=2,
                    ),
                    encoding="utf-8",
                )
            except OSError as exc:
                self._log(f"⚠️ DV-Recovery-Status konnte nicht geschrieben werden: {exc}", "warn")
            self._archiviert += 1
            self._log(
                f"📦 DV-Remux-Kandidat zur Diagnose erhalten: {target}",
                "warn",
            )
            return str(target)
        except OSError as exc:
            self._log(f"⚠️ DV-Remux-Kandidat konnte nicht archiviert werden: {exc}", "warn")
            return None

    def replace_output_if_needed(self, input_path: str, output_path: str) -> DVOutputInstallResult:
        w = self.worker
        allowed, preserved_path = validate_output_size_policy(
            input_path=input_path,
            output_path=output_path,
            logger=self._log,
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
            self._log(f"Ersetzen fehlgeschlagen: {exc}", "error")
            self._log(traceback.format_exc(), "error")
            return DVOutputInstallResult(False, output_path)
        finally:
            self.cleanup_temp_dir(input_path)

    def _handle_rejected_output(self, input_path: str, output_path: str, preserved_path: Path | None) -> None:
        w = self.worker
        if preserved_path is not None:
            self._archiviert += 1
            self._log(
                f"📦 DV-Ausgabe wegen Größenregel in Archiv/ abgelegt: {preserved_path.name}",
                "warn",
            )
        else:
            self._log(
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
            log=self._log,
            min_size=1024,
            abort_check=lambda: bool(
                getattr(w, "abort_requested", False)
                and getattr(w, "abort_type", None) == "sofort"
            ),
        )

    def cleanup_temp_dir(self, input_path: str) -> None:
        temp_dir = Path(input_path).parent / "__temp_dv_remux__"
        try:
            temp_dir.rmdir()
        except FileNotFoundError:
            return
        except OSError as exc:
            if temp_dir.exists():
                self._log(
                    f"Temporärer DV-Remux-Ordner konnte nicht entfernt werden: "
                    f"{temp_dir.name} - {exc}",
                    "warn",
                )

    def cleanup_incomplete(self, input_path: str, output_path: str | None) -> None:
        """Delete only known staging paths; committed/archived outputs are protected."""
        if output_path:
            candidate = Path(output_path)
            source = Path(input_path)
            safe_to_delete = self.is_known_staging(input_path, output_path)
            if candidate.exists() and safe_to_delete:
                try:
                    candidate.unlink()
                except OSError as exc:
                    self._log(
                        f"Unvollständige DV-Ausgabedatei konnte nicht gelöscht werden: "
                        f"{candidate.name} - {exc}",
                        "warn",
                    )
            elif candidate.exists() and not safe_to_delete:
                self._log(
                    f"DV-Cleanup schützt bereits installierte/archivierte Ausgabe: {candidate.name}",
                    "warn",
                )
        self.cleanup_temp_dir(input_path)


__all__ = ["DVOutputInstallResult", "DVOutputManager"]
