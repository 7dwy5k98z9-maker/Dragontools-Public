# -*- coding: utf-8 -*-
from __future__ import annotations

import math
import subprocess
from pathlib import Path

from ..core.media_hdr_detection import detect_hdr_from_ffprobe_stream, parse_dolby_vision_from_ffprobe_stream
from ..core.media_metadata import normalize_video_codec
from ..core.transaction_identity import stat_identity
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
from .timestamp_diagnostics import wrap_message
from .owned_probe import owned_probe_runner
from .verification_control import require_running


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
        duration_max_shortfall_s: float = 3.0,
        duration_max_overrun_s: float = 3.0,
        worker=None,
    ) -> None:
        self._ffprobe_path = ffprobe_path
        self._worker = worker
        self._min_size_bytes = max(1, int(min_size_bytes or 1024))
        self._duration_min_ratio = max(0.01, float(duration_min_ratio or 0.90))
        self._duration_max_ratio = max(self._duration_min_ratio, float(duration_max_ratio or 1.25))
        self._duration_max_extra_s = max(0.0, float(duration_max_extra_s or 0.0))
        self._duration_max_shortfall_s = max(0.0, float(duration_max_shortfall_s or 0.0))
        self._duration_max_overrun_s = max(0.0, float(duration_max_overrun_s or 0.0))

    def probe_chapter_count(self, output_path: str | Path) -> int:
        probe = probe_output(
            Path(output_path),
            ffprobe_path=self._ffprobe_path,
            run_process=self._probe_runner(),
            no_window_kwargs=_no_window_kwargs(),
        )
        return len(probe.chapters)

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
        try:
            require_running(worker=self._worker)
            self._apply_file_checks(result, path, container)
        except (OSError, RuntimeError) as exc:
            result.messages.append(f'Ausgabeprüfung nicht verfügbar: {exc}')
            self._mark_unprobeable(result, source_has_audio, expected_contract)
            return result
        if not result.exists:
            return result
        if not result.size_ok:
            self._mark_unprobeable(result, source_has_audio, expected_contract)
            return result

        try:
            verified_identity = stat_identity(path)
            probe = probe_output(
                path,
                ffprobe_path=self._ffprobe_path,
                run_process=self._probe_runner(),
                no_window_kwargs=_no_window_kwargs(),
            )
            require_running(worker=self._worker)
            if stat_identity(path) != verified_identity:
                raise OSError('Ausgabedatei wurde während der semantischen Prüfung verändert.')
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

    def _probe_runner(self):
        return subprocess.run if self._worker is None else owned_probe_runner(self._worker)

    def _apply_file_checks(self, result: WorkflowVerifyResult, path: Path, container: str) -> None:
        result.exists = path.is_file()
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
        attachments = [stream for stream in probe.streams if stream.get("codec_type") == "attachment"]
        attachments.extend(probe.attached_picture_streams)
        data_streams = [stream for stream in probe.streams if stream.get("codec_type") == "data"]
        result.format_name = probe.format_name
        result.duration_s = probe.duration_s
        result.video_stream_count = len(videos)
        result.audio_stream_count = len(audios)
        result.subtitle_stream_count = len(subtitles)
        result.attachment_stream_count = len(attachments)
        result.data_stream_count = len(data_streams)
        result.chapter_count = len(getattr(probe, "chapters", ()) or ())
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
            result.dolby_vision_profile = parse_dolby_vision_from_ffprobe_stream(video)['dv_profile_major']
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
            warning = wrap_message(
                expected_duration_ms / 1000.0 if expected_duration_ms else None,
                probe.duration_s, container=container, stream="Container; Stream nicht bestimmt",
            )
            if warning:
                result.messages.append(warning)
        if expected_contract is not None:
            apply_contract(
                result, expected_contract, video_streams=videos, audio_streams=audios,
                subtitle_streams=subtitles, attachment_streams=attachments, data_streams=data_streams,
            )
            expected_container = self._normalize_contract_container(expected_contract.container)
            requested_container = self._normalize_contract_container(container)
            if expected_container and expected_container != requested_container:
                result.contract_ok = False
                result.contract_non_geometry_ok = False
                result.messages.append(
                    "Container-Vertrag verletzt: "
                    f"geplant {expected_container}, Workflow prueft/committet {requested_container or '<unbekannt>'}."
                )

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
        if duration_s is None:
            return False
        try:
            duration_s = float(duration_s)
        except (TypeError, ValueError):
            return False
        if not math.isfinite(duration_s) or duration_s <= 0:
            return False
        if not expected_duration_ms or expected_duration_ms <= 0:
            return True
        expected_s = expected_duration_ms / 1000.0
        # Die Prozentgrenze bleibt als konfigurierbarer Outer Guard erhalten,
        # aber ein finaler Replace-Gate darf bei langen Filmen nicht Minuten an
        # fehlendem Material akzeptieren.  Maximal wenige Sekunden Shortfall
        # decken Container-/VFR-Rundung ab, nicht abgeschnittene Encodes.
        lower = max(
            expected_s * self._duration_min_ratio,
            expected_s - self._duration_max_shortfall_s,
        )
        configured_upper = max(
            expected_s + self._duration_max_extra_s,
            expected_s * self._duration_max_ratio,
        )
        upper = min(configured_upper, expected_s + self._duration_max_overrun_s)
        return lower <= duration_s <= upper

    @staticmethod
    def _normalize_contract_container(value: str | None) -> str:
        normalized = str(value or "").strip().lower().lstrip(".")
        if normalized in {"mov", "m4v"}:
            return "mp4"
        if normalized in {"matroska", "webm"}:
            return "mkv"
        return normalized
