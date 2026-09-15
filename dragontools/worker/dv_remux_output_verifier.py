# -*- coding: utf-8 -*-
"""Fail-closed verification for final Dolby-Vision remux containers."""
from __future__ import annotations

from dataclasses import dataclass

from ..core.media_analyzer import inspect_dynamic_hdr_with_mediainfo
from .media_contract_types import ExpectedMediaContract
from .output_verifier import OutputVerifier


@dataclass(frozen=True, slots=True)
class DVRemuxVerification:
    ok: bool
    messages: tuple[str, ...]


class DVRemuxOutputVerifier:
    def __init__(self, *, tools) -> None:
        self._tools = tools
        self._verifier = OutputVerifier(ffprobe_path=str(tools.ffprobe), min_size_bytes=1024)

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
        result = self._verifier.verify(
            output_path, container, expected_duration_ms=expected_duration_ms,
            source_has_audio=source_has_audio if expected_contract is None else expected_contract.audio_stream_count > 0,
            expected_contract=expected_contract, verified_dolby_vision=dv_ok,
        )
        messages = list(result.messages or []) + messages
        return DVRemuxVerification(ok=bool(result.ok and dv_ok), messages=tuple(messages))


def _profile_major(value) -> int | None:
    if value in (None, "", "Ja"):
        return None
    try:
        return int(str(value).strip().split(".", 1)[0])
    except (TypeError, ValueError):
        return None
