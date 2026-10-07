# -*- coding: utf-8 -*-
"""Fail-closed verification for final Dolby-Vision remux containers."""
from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path

from ..core.media_analyzer import inspect_dynamic_hdr_with_mediainfo
from .dv_pipeline_timeouts import timeout_hevc_extract, timeout_rpu_extract
from .media_contract_types import ExpectedMediaContract
from .output_verifier import OutputVerifier


@dataclass(frozen=True, slots=True)
class DVRemuxVerification:
    ok: bool
    messages: tuple[str, ...]


class DVRemuxOutputVerifier:
    def __init__(self, *, tools, process_runner=None, worker=None) -> None:
        self._tools = tools
        self._process_runner = process_runner
        self._verifier = OutputVerifier(ffprobe_path=str(tools.ffprobe), min_size_bytes=1024, worker=worker)

    def verify(
        self, *, output_path: str, container: str, expected_duration_ms: int | None,
        source_has_audio: bool = False,
        expected_contract: ExpectedMediaContract | None = None,
    ) -> DVRemuxVerification:
        inspection = inspect_dynamic_hdr_with_mediainfo(output_path, self._tools)
        messages: list[str] = []
        if not inspection.conclusive:
            detail = next((item for item in inspection.warnings if item), "MediaInfo lieferte kein eindeutiges Ergebnis")
            messages.append(f"Dolby-Vision-Nachprüfung nicht eindeutig: {detail}.")
            dv_ok = False
        else:
            dv_ok = bool(inspection.dolby_vision)
            if not dv_ok:
                messages.append("Dolby Vision ist im finalen Remux nicht nachweisbar.")
            expected_profile = (
                expected_contract.expected_dolby_vision_profile
                if expected_contract is not None
                else None
            )
            if dv_ok and expected_profile is not None:
                actual_profile = _profile_major(inspection.dolby_vision_profile)
                if actual_profile != int(expected_profile):
                    dv_ok = False
                    messages.append(
                        "Dolby-Vision-Profil abweichend: "
                        f"erwartet P{expected_profile}, gefunden "
                        f"{('P' + str(actual_profile)) if actual_profile is not None else '<unbekannt>'}."
                    )

        # Container/MediaInfo signalling alone is not proof that the final HEVC
        # payload still contains Dolby-Vision RPU metadata.  The production
        # remux path therefore extracts the final video again and asks dovi_tool
        # to prove that a non-empty RPU can be recovered.  Unit/legacy callers
        # without a process runner keep their historical verification surface.
        rpu_ok = True
        if dv_ok and self._process_runner is not None:
            rpu_ok, rpu_message = self._verify_final_rpu(output_path, container)
            if not rpu_ok:
                messages.append(rpu_message)

        result = self._verifier.verify(
            output_path, container, expected_duration_ms=expected_duration_ms,
            source_has_audio=source_has_audio if expected_contract is None else expected_contract.audio_stream_count > 0,
            expected_contract=expected_contract, verified_dolby_vision=bool(dv_ok and rpu_ok),
        )
        messages = list(result.messages or []) + messages
        return DVRemuxVerification(ok=bool(result.ok and dv_ok and rpu_ok), messages=tuple(messages))

    def _verify_final_rpu(self, output_path: str, container: str) -> tuple[bool, str]:
        ffmpeg = str(getattr(self._tools, "ffmpeg", "") or "").strip()
        dovi_tool = str(getattr(self._tools, "dovi_tool", "") or "").strip()
        if not ffmpeg or not dovi_tool:
            return False, "Finale Dolby-Vision-RPU konnte nicht geprüft werden: ffmpeg/dovi_tool fehlt."

        with tempfile.TemporaryDirectory(prefix="dragontools_dv_verify_") as tmp_dir:
            tmp = Path(tmp_dir)
            hevc = tmp / "final.hevc"
            rpu = tmp / "final.rpu"
            cmd = [
                ffmpeg, "-y", "-nostdin", "-loglevel", "error",
                "-i", str(output_path), "-map", "0:v:0", "-c:v", "copy",
                "-bsf:v", "hevc_mp4toannexb", "-an", "-sn", "-dn",
                "-f", "hevc", str(hevc),
            ]
            try:
                rc, _stdout, stderr = self._process_runner.run_abortable_capture(
                    cmd, timeout_s=timeout_hevc_extract()
                )
            except (OSError, ValueError, RuntimeError) as exc:
                return False, f"Finale Dolby-Vision-RPU-Prüfung: HEVC-Extraktion fehlgeschlagen: {exc}"
            if rc != 0 or not hevc.exists() or hevc.stat().st_size <= 0:
                detail = str(stderr or "").strip().splitlines()[-1:]
                suffix = f" ({detail[0]})" if detail else ""
                return False, f"Finale Dolby-Vision-RPU-Prüfung: HEVC-Extraktion fehlgeschlagen{suffix}."

            try:
                rc, _stdout, stderr = self._process_runner.run_abortable_capture(
                    [dovi_tool, "extract-rpu", "-i", str(hevc), "-o", str(rpu)],
                    timeout_s=timeout_rpu_extract(),
                )
            except (OSError, ValueError, RuntimeError) as exc:
                return False, f"Finale Dolby-Vision-RPU konnte nicht extrahiert werden: {exc}"
            if rc != 0 or not rpu.exists() or rpu.stat().st_size <= 0:
                detail = str(stderr or "").strip().splitlines()[-1:]
                suffix = f" ({detail[0]})" if detail else ""
                return False, f"Finale Dolby-Vision-RPU ist im HEVC-Bitstream nicht nachweisbar{suffix}."
        return True, ""


def _profile_major(value) -> int | None:
    if value in (None, "", "Ja"):
        return None
    try:
        return int(str(value).strip().split(".", 1)[0])
    except (TypeError, ValueError):
        return None
