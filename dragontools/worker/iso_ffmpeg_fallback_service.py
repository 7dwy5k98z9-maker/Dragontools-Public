# -*- coding: utf-8 -*-
from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable

from ..core.timeout_settings import get_timeout
from ..core.output_timestamps import build_output_timestamp_args
from ..core.move_transaction import publish_staged_no_replace
from .iso_disc_inspector import ISODiscInspector, quote_concat_path
from .iso_makemkv_service import tool_exists
from .iso_models import ISOExtractionResult, ISOUserAbortError, FFMPEG_FALLBACK_TITLE_ID
from .tool_runner import run_tool
from .output_verifier import OutputVerifier
from .utility_output_workspace import VerifiedOutputWorkspace
from .utility_copy_contract import probe_copy_source
from .iso_output_publication import require_iso_not_aborted
from ..core.transaction_identity import path_receipt, receipt_matches
from ..core.callback_dispatch import best_effort_callback

ProgressFn = Callable[[str, int, object], None]
RunFFmpegFn = Callable[[list[str], str | None], tuple[int, list[str]]]


class ISOFFmpegFallbackService:
    """Lossless FFmpeg fallback for directly readable, unencrypted disc data."""

    def __init__(self, *, tools, inspector: ISODiscInspector, worker, log, progress: ProgressFn) -> None:
        self._tools = tools
        self._inspector = inspector
        self._worker = worker
        self._log = log
        self._progress = progress

    def ensure_ffmpeg(self) -> str:
        tool = getattr(self._tools, "ffmpeg", "") or ""
        if not tool_exists(tool):
            raise RuntimeError("FFmpeg wurde fuer den ISO-Fallback nicht gefunden.")
        return tool

    def run(self, cmd: list[str], progress_path: str | None = None) -> tuple[int, list[str]]:
        self._log("▶ " + " ".join(cmd), "info")
        lines: list[str] = []

        def _line(raw: str) -> None:
            line = raw.rstrip()
            lines.append(line)
            if line:
                self._log(line, "info")
                if progress_path:
                    self._progress(progress_path, 45, None)

        result = run_tool(
            cmd,
            label="ISO FFmpeg-Fallback",
            timeout_s=get_timeout("worker_media_process"),
            timeout_mode="inactivity",
            worker=self._worker,
            log=self._log,
            merge_stderr=True,
            stdout_line=_line,
        )
        if result.aborted:
            raise ISOUserAbortError("Abgebrochen")
        if result.timed_out:
            raise RuntimeError('ISO-Fallback wurde wegen Zeitüberschreitung beendet.')
        return result.returncode, lines

    def extract(
        self,
        path: str,
        output_dir: str,
        *,
        run_ffmpeg: RunFFmpegFn | None = None,
    ) -> ISOExtractionResult:
        try:
            ffmpeg = self.ensure_ffmpeg()
        except (OSError, RuntimeError, ValueError) as exc:
            self._log(f"❌ {exc}", "error")
            return ISOExtractionResult(ok=False, error=str(exc))

        candidate, candidate_error = self._inspector.ffmpeg_fallback_candidate(path)
        if not candidate:
            error = candidate_error or "FFmpeg-Fallback nicht möglich: keine direkt lesbare ISO-/Disc-Struktur gefunden."
            self._log(f"❌ {error}", "error")
            return ISOExtractionResult(ok=False, error=error)

        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        output = self._inspector.unique_fallback_output(path, out_dir)
        workspace = VerifiedOutputWorkspace(out_dir, self._log, prefix='.__dragontools_iso_ffmpeg_')
        staging = workspace.root / 'fallback.mkv'
        self._progress(path, 35, [FFMPEG_FALLBACK_TITLE_ID])
        self._log(
            "⚠️ FFmpeg-Fallback ist aktiv. "
            "Dieser Weg remuxt ohne Re-Encoding, ist aber bei Menüs, Playlists, Kapiteln, "
            "Untertiteln und verschlüsselten Discs fehleranfälliger als MakeMKV.",
            "warn",
        )

        temp_list: Path | None = None
        try:
            sources = self._source_paths(candidate)
            receipts = {source: path_receipt(source) for source in sources}
            contract, duration_ms, chapter_count = self._source_contract(candidate)
            self._require_source_receipts(receipts)
            require_iso_not_aborted(self._worker)
            if candidate["mode"] == "concat":
                files = list(candidate.get("files") or [])
                if not files:
                    raise RuntimeError("DVD-Fallback ohne VOB-Dateien.")
                with tempfile.NamedTemporaryFile(
                    "w",
                    encoding="utf-8",
                    suffix=".ffconcat.txt",
                    dir=str(workspace.root),
                    delete=False,
                ) as handle:
                    temp_list = Path(handle.name)
                    for file in files:
                        handle.write(quote_concat_path(file) + "\n")
                cmd = [
                    ffmpeg, "-hide_banner", "-nostdin", "-n", "-fflags", "+genpts",
                    "-f", "concat", "-safe", "0", "-i", str(temp_list),
                    "-map", "0", "-c", "copy", "-map_metadata", "0", str(staging),
                ]
            else:
                src = Path(candidate["path"])
                cmd = [
                    ffmpeg, "-hide_banner", "-nostdin", "-n", "-fflags", "+genpts",
                    "-i", str(src), "-map", "0", "-c", "copy", "-map_metadata", "0", str(staging),
                ]

            cmd[-1:-1] = build_output_timestamp_args("mkv")
            runner = run_ffmpeg or self.run
            rc, lines = runner(cmd, progress_path=path)
            if isinstance(rc, bool) or not isinstance(rc, int) or rc != 0:
                detail = "\n".join(lines[-8:]).strip()
                error = f"FFmpeg-Fallback fehlgeschlagen (Exitcode {rc})." + (f"\n{detail}" if detail else "")
                self._log(f"❌ FFmpeg-Fallback fehlgeschlagen (Exitcode {rc}).", "error")
                return ISOExtractionResult(ok=False, error=error)
            if not staging.exists() or staging.stat().st_size <= 0:
                error = "FFmpeg-Fallback erzeugte keine gültige Ausgabedatei."
                self._log(f"❌ {error}", "error")
                return ISOExtractionResult(ok=False, error=error)

            self._verify_stage(staging, contract, duration_ms, chapter_count)
            workspace.mark_verified(staging)
            require_iso_not_aborted(self._worker)
            self._require_source_receipts(receipts)
            if not receipt_matches(staging, workspace.verified[staging]):
                raise OSError("Geprüfte ISO-Fallback-Ausgabe wurde verändert.")
            try:
                publish_staged_no_replace(staging, output)
            except FileExistsError:
                error = f"FFmpeg-Fallback-Ziel wurde zwischenzeitlich belegt: {output.name}"
                self._log(f"❌ {error}", "error")
                return ISOExtractionResult(ok=False, error=error)

            workspace.published = True
            best_effort_callback(self._progress, path, 95, [FFMPEG_FALLBACK_TITLE_ID])
            best_effort_callback(self._log, f"✅ FFmpeg-Fallback abgeschlossen: {output.name}", "success")
            return ISOExtractionResult(ok=True, extracted_files=[str(output)])
        except ISOUserAbortError:
            raise
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            error = f"FFmpeg-Fallback fehlgeschlagen: {exc}"
            self._log(f"❌ {error}", "error")
            return ISOExtractionResult(ok=False, error=error)
        finally:
            workspace.__exit__()

    def _verify_stage(self, staging, contract, duration_ms, chapter_count):
        verifier = OutputVerifier(ffprobe_path=str(getattr(self._tools, "ffprobe", "") or ""), min_size_bytes=1024, worker=self._worker)
        verification = verifier.verify(str(staging), "mkv",
            source_has_audio=bool(contract.audio_stream_count), expected_contract=contract,
            expected_duration_ms=duration_ms)
        if verification.ok and getattr(verification, 'chapter_count', chapter_count) != chapter_count:
            raise RuntimeError("ISO-Fallback verändert die Kapitelanzahl.")
        if not verification.ok:
            detail = "; ".join(verification.messages or []) or "unbekannter Verifikationsfehler"
            error = f"FFmpeg-Fallback-Ausgabe ungültig: {detail}"
            self._log(f"❌ {error}", "error")
            raise RuntimeError(error)

    @staticmethod
    def _source_paths(candidate):
        return [Path(path) for path in candidate['files']] if candidate['mode'] == 'concat' else [Path(candidate['path'])]

    @staticmethod
    def _require_source_receipts(receipts):
        for source, receipt in receipts.items():
            if not receipt_matches(source, receipt):
                raise OSError("ISO-Fallback-Quelldatei wurde während der Verarbeitung verändert.")

    def _source_contract(self, candidate):
        proofs = [probe_copy_source(path, self._tools, self._worker) for path in self._source_paths(candidate)]
        if not proofs:
            raise RuntimeError("ISO-Fallback besitzt keinen Quellvertrag.")
        first = proofs[0][0]
        if any(proof[0] != first for proof in proofs[1:]):
            raise RuntimeError("DVD-Teildateien besitzen unterschiedliche Medienverträge; Fallback abgelehnt.")
        if len(proofs) > 1 and any(proof[2] for proof in proofs):
            raise RuntimeError("Kapitel mehrerer DVD-Teildateien können nicht sicher zusammengefügt werden.")
        duration_ms = int(sum(proof[1] for proof in proofs) * 1000) or None
        return first, duration_ms, sum(proof[2] for proof in proofs)
