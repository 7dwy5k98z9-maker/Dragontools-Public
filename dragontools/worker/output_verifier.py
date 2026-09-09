# -*- coding: utf-8 -*-
from __future__ import annotations

import subprocess
from pathlib import Path

from ..core.media_hdr_detection import detect_hdr_from_ffprobe_stream
from ..core.media_metadata import normalize_video_codec
from ..core.process_runner import subprocess_no_window_kwargs as _no_window_kwargs
from .media_contract import ExpectedMediaContract
from .output_contract_verifier import (
    apply_contract,
    compare_audio_tracks,
    compare_subtitle_tracks,
    video_bit_depth,
)
from .output_probe import probe_output
from .workflow_engine import WorkflowVerifyResult


class OutputVerifier:
    """Prüft finale Ausgaben gegen Dateiplausibilität und Medienvertrag."""

    def __init__(
        self,
        *,
        ffprobe_path: str,
        min_size_bytes: int = 1024,
        duration_min_ratio: float = 0.90,
        duration_max_ratio: float = 1.25,
        duration_max_extra_s: float = 60.0,
    ) -> None:
        self._ffprobe_path = ffprobe_path
        self._min_size_bytes = max(1, int(min_size_bytes or 1024))
        self._duration_min_ratio = max(0.01, float(duration_min_ratio or 0.90))
        self._duration_max_ratio = max(self._duration_min_ratio, float(duration_max_ratio or 1.25))
        self._duration_max_extra_s = max(0.0, float(duration_max_extra_s or 0.0))

    def verify(
        self,
        output_path: str | None,
        container: str,
        *,
        expected_duration_ms: int | None = None,
        source_has_audio: bool = False,
        expected_contract: ExpectedMediaContract | None = None,
        verified_hdr10plus: bool = False,
        verified_dolby_vision: bool = False,
    ) -> WorkflowVerifyResult:
        result = WorkflowVerifyResult(messages=[])
        if not output_path:
            result.messages.append("Kein Ausgabepfad vorhanden.")
            return result

        path = Path(output_path)
        self._apply_file_checks(result, path, container)
        if not result.exists:
            return result
        if not result.size_ok:
            self._mark_unprobeable(result, source_has_audio, expected_contract)
            return result

        try:
            probe = probe_output(
                path,
                ffprobe_path=self._ffprobe_path,
                run_process=subprocess.run,
                no_window_kwargs=_no_window_kwargs(),
            )
            self._apply_probe_result(
                result,
                probe,
                container=container,
                expected_duration_ms=expected_duration_ms,
                source_has_audio=source_has_audio,
                expected_contract=expected_contract,
                verified_hdr10plus=verified_hdr10plus,
                verified_dolby_vision=verified_dolby_vision,
            )
        except Exception as exc:
            result.probe_ok = False
            result.contract_ok = expected_contract is None
            result.metadata_ok = expected_contract is None
            result.messages.append(f"ffprobe-Prüfung fehlgeschlagen: {exc}")
        return result

    def _apply_file_checks(self, result: WorkflowVerifyResult, path: Path, container: str) -> None:
        result.exists = path.exists()
        result.size_ok = result.exists and path.stat().st_size >= self._min_size_bytes
        result.container_ok = path.suffix.lower() == f".{container.lower()}"
        if not result.exists:
            result.messages.append("Ausgabedatei fehlt.")
            return
        if not result.size_ok:
            result.messages.append("Ausgabedatei ist unplausibel klein.")
        if not result.container_ok:
            result.messages.append(f"Container-Endung passt nicht: erwartet .{container.lower()}, gefunden {path.suffix or '<ohne>'}.")

    def _apply_probe_result(
        self,
        result: WorkflowVerifyResult,
        probe,
        *,
        container: str,
        expected_duration_ms: int | None,
        source_has_audio: bool,
        expected_contract: ExpectedMediaContract | None,
        verified_hdr10plus: bool,
        verified_dolby_vision: bool,
    ) -> None:
        videos, audios, subtitles = probe.video_streams, probe.audio_streams, probe.subtitle_streams
        result.format_name = probe.format_name
        result.duration_s = probe.duration_s
        result.video_stream_count = len(videos)
        result.audio_stream_count = len(audios)
        result.subtitle_stream_count = len(subtitles)
        result.probe_ok = probe.usable
        result.video_ok = bool(videos)
        result.audio_ok = True if expected_contract is not None else ((not source_has_audio) or bool(audios))
        result.duration_ok = self._duration_plausible(probe.duration_s, expected_duration_ms=expected_duration_ms)

        if videos:
            video = videos[0]
            result.video_codec = normalize_video_codec(video.get("codec_name"))
            result.video_bit_depth = video_bit_depth(video)
            is_hdr, has_hdr10plus, dv_profile = detect_hdr_from_ffprobe_stream(video)
            result.has_hdr = bool(is_hdr)
            result.has_hdr10plus = bool(has_hdr10plus) or bool(verified_hdr10plus)
            result.has_dolby_vision = dv_profile is not None or bool(verified_dolby_vision)
            if result.has_hdr10plus or result.has_dolby_vision:
                result.has_hdr = True

        if not self._format_matches_container(result.format_name, container):
            result.container_ok = False
            result.messages.append(f"ffprobe-Container passt nicht: erwartet {container.lower()}, gefunden {result.format_name or '<unbekannt>'}.")
        if not result.probe_ok:
            result.messages.append("ffprobe liefert keine verwertbaren Formatdaten.")
        if not result.video_ok:
            result.messages.append("Kein Videostream in der Ausgabedatei gefunden.")
        if not result.audio_ok:
            result.messages.append("Quelle hatte Audio, aber die Ausgabe enthält keine Audiospur.")
        if not result.duration_ok:
            result.messages.append("Ausgabedauer ist nicht plausibel.")
        if expected_contract is not None:
            apply_contract(result, expected_contract, video_streams=videos, audio_streams=audios, subtitle_streams=subtitles)

    @staticmethod
    def _mark_unprobeable(result, source_has_audio, expected_contract) -> None:
        result.probe_ok = False
        result.video_ok = False
        result.audio_ok = not source_has_audio if expected_contract is None else expected_contract.audio_stream_count == 0
        result.subtitle_ok = expected_contract is None or not expected_contract.subtitle_tracks
        result.contract_ok = expected_contract is None
        result.metadata_ok = expected_contract is None
        result.duration_ok = False

    # Private Legacy-Delegates bleiben fuer bestehende Tests/Erweiterungen stabil.
    _apply_contract = staticmethod(apply_contract)
    _compare_audio_tracks = staticmethod(compare_audio_tracks)
    _compare_subtitle_tracks = staticmethod(compare_subtitle_tracks)
    _video_bit_depth = staticmethod(video_bit_depth)

    @staticmethod
    def _format_matches_container(format_name: str, container: str) -> bool:
        names = {part.strip().lower() for part in str(format_name or "").split(",") if part.strip()}
        target = str(container or "").strip().lower()
        if not names:
            return False
        if target == "mkv":
            return bool(names & {"matroska", "webm"})
        if target in {"mp4", "m4v", "mov"}:
            return bool(names & {"mov", "mp4", "m4a", "3gp", "3g2", "mj2"})
        return target in names

    def _duration_plausible(self, duration_s: float | None, *, expected_duration_ms: int | None) -> bool:
        if duration_s is None or duration_s <= 0:
            return False
        if not expected_duration_ms or expected_duration_ms <= 0:
            return True
        expected_s = expected_duration_ms / 1000.0
        lower = expected_s * self._duration_min_ratio
        upper = max(expected_s + self._duration_max_extra_s, expected_s * self._duration_max_ratio)
        return lower <= duration_s <= upper
