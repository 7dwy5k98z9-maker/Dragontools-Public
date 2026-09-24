# -*- coding: utf-8 -*-
"""Language detection and safe stream-metadata correction for Fix Queue."""
from __future__ import annotations

import json
from pathlib import Path
import tempfile
from typing import Callable

from ..core.language_detection import (
    FasterWhisperLanguageDetector,
    LanguageDetectionResult,
    LanguageEvidence,
    combine_language_evidence,
    detect_text_language,
)
from ..core.media_library_fix_queue import MediaLibraryFixIssue
from .media_stream_metadata_guard import edit_queued_track
from .tool_runner import run_tool
from ..core.settings_storage import SET_KEY_WHISPER_MODEL_DIR, SET_KEY_WHISPER_USE_LOCAL_MODEL
from ..core.settings_media_library import (
    DEFAULT_MEDIA_LIBRARY_LANGUAGE_AUDIO_SAMPLES,
    DEFAULT_MEDIA_LIBRARY_LANGUAGE_MIN_CONFIDENCE,
    DEFAULT_MEDIA_LIBRARY_LANGUAGE_MODEL,
    DEFAULT_MEDIA_LIBRARY_LANGUAGE_SAMPLE_SECONDS,
    SET_KEY_MEDIA_LIBRARY_LANGUAGE_AUDIO_SAMPLES,
    SET_KEY_MEDIA_LIBRARY_LANGUAGE_MIN_CONFIDENCE,
    SET_KEY_MEDIA_LIBRARY_LANGUAGE_MODEL,
    SET_KEY_MEDIA_LIBRARY_LANGUAGE_SAMPLE_SECONDS,
)
from ..core.track_titles import build_track_title, track_title_is_generic


LogFn = Callable[[str, str], None] | None
_BITMAP_SUBTITLE_CODECS = {"hdmv_pgs_subtitle", "dvd_subtitle", "pgs", "vobsub"}
_TEXT_SUBTITLE_CODECS = {"subrip", "srt", "ass", "ssa", "webvtt", "vtt", "mov_text", "subt"}


class MediaStreamLanguageService:
    def __init__(self, *, settings, tools, log: LogFn = None, worker=None) -> None:
        self.settings = settings
        self.tools = tools
        self.log = log
        self.worker = worker
        self.min_probability = self._setting_int(
            SET_KEY_MEDIA_LIBRARY_LANGUAGE_MIN_CONFIDENCE,
            DEFAULT_MEDIA_LIBRARY_LANGUAGE_MIN_CONFIDENCE,
            minimum=50,
            maximum=99,
        ) / 100.0
        self.audio_samples = self._setting_int(
            SET_KEY_MEDIA_LIBRARY_LANGUAGE_AUDIO_SAMPLES,
            DEFAULT_MEDIA_LIBRARY_LANGUAGE_AUDIO_SAMPLES,
            minimum=1,
            maximum=7,
        )
        self.sample_seconds = self._setting_int(
            SET_KEY_MEDIA_LIBRARY_LANGUAGE_SAMPLE_SECONDS,
            DEFAULT_MEDIA_LIBRARY_LANGUAGE_SAMPLE_SECONDS,
            minimum=5,
            maximum=60,
        )
        self.model_name = self._setting_str(
            SET_KEY_MEDIA_LIBRARY_LANGUAGE_MODEL,
            DEFAULT_MEDIA_LIBRARY_LANGUAGE_MODEL,
        )
        self.model_path = self._setting_str(SET_KEY_WHISPER_MODEL_DIR, "")
        self.use_local_model = self._setting_bool(
            SET_KEY_WHISPER_USE_LOCAL_MODEL,
            bool(self.model_path),
        )
        self._whisper: FasterWhisperLanguageDetector | None = None

    def detect(self, issue: MediaLibraryFixIssue) -> LanguageDetectionResult:
        stream_type = str(issue.stream_type or "").casefold()
        if stream_type == "audio":
            return self._detect_audio(issue)
        if stream_type == "subtitle":
            return self._detect_subtitle(issue)
        return LanguageDetectionResult("", 0.0, False, (), "Nicht unterstützter Streamtyp.")

    def apply_detected_language(self, issue: MediaLibraryFixIssue, result: LanguageDetectionResult) -> tuple[bool, str]:
        if not result.accepted or not result.language:
            return False, result.reason or "Spracherkennung war nicht sicher genug."
        title = None
        if track_title_is_generic(issue.track_title):
            title = build_track_title(
                stream_type=issue.stream_type,
                language=result.language,
                codec=issue.codec,
                channels=issue.channels,
                bitrate=issue.bitrate,
                forced=issue.forced,
            )
        return self._apply_metadata(issue, language=result.language, title=title)

    def apply_track_title(self, issue: MediaLibraryFixIssue) -> tuple[bool, str]:
        language = str(issue.language or "").strip()
        if not language or language.casefold() in {"und", "unk", "unknown", "undefined"}:
            return False, "Tracktitel wird nicht erzeugt, solange die Sprache unbekannt ist."
        if not track_title_is_generic(issue.track_title):
            return True, "Vorhandener benutzerdefinierter Tracktitel bleibt unverändert."
        title = build_track_title(
            stream_type=issue.stream_type,
            language=language,
            codec=issue.codec,
            channels=issue.channels,
            bitrate=issue.bitrate,
            forced=issue.forced,
        )
        return self._apply_metadata(issue, title=title)

    def _apply_metadata(
        self,
        issue: MediaLibraryFixIssue,
        *,
        language: str | None = None,
        title: str | None = None,
    ) -> tuple[bool, str]:
        if self._abort_requested():
            return False, "Track-Korrektur wurde abgebrochen."
        path = Path(issue.path)
        if path.suffix.casefold() != ".mkv":
            detected = f"{language} erkannt; " if language else ""
            return False, detected + "direkte Track-Korrektur ist in Patch I nur für MKV aktiviert."
        return edit_queued_track(
            issue, tools=self.tools, worker=self.worker, language=language, title=title,
        )

    def _detect_audio(self, issue: MediaLibraryFixIssue) -> LanguageDetectionResult:
        if issue.stream_index is None:
            return LanguageDetectionResult("", 0.0, False, (), "Audiostream besitzt keinen eindeutigen Streamindex.")
        if not FasterWhisperLanguageDetector.available():
            return LanguageDetectionResult(
                "", 0.0, False, (),
                "faster-whisper ist nicht installiert; Audio-Spracherkennung bleibt optional deaktiviert.",
            )
        detector = self._whisper_detector()
        duration = float(issue.duration_s or 0.0)
        if duration <= 0:
            duration = self._probe_duration(issue.path)
        starts = _sample_starts(duration, self.audio_samples, self.sample_seconds)
        evidence: list[LanguageEvidence] = []
        with tempfile.TemporaryDirectory(prefix="dragon_lang_") as tmp:
            for sample_no, start in enumerate(starts, start=1):
                if self._abort_requested():
                    break
                wav = Path(tmp) / f"sample_{sample_no}.wav"
                if not self._extract_audio_sample(issue.path, issue.stream_index, start, wav):
                    continue
                item = detector.detect_file(str(wav))
                evidence.append(LanguageEvidence(item.language, item.probability, f"audio-{sample_no}"))
                self._log(
                    f"Spracherkennung Sample {sample_no}: {item.language or '?'} {item.probability * 100:.1f}%",
                    "info",
                )
        if self._abort_requested():
            return LanguageDetectionResult("", 0.0, False, (), "Spracherkennung abgebrochen.")
        return combine_language_evidence(evidence, min_probability=self.min_probability)

    def _detect_subtitle(self, issue: MediaLibraryFixIssue) -> LanguageDetectionResult:
        codec = str(issue.codec or "").casefold()
        if codec in _BITMAP_SUBTITLE_CODECS:
            return LanguageDetectionResult(
                "", 0.0, False, (),
                "Bilduntertitel benötigen OCR; das folgt separat in Patch J.",
            )
        if codec and codec not in _TEXT_SUBTITLE_CODECS:
            return LanguageDetectionResult("", 0.0, False, (), f"Untertitelcodec {codec} wird nicht als Text erkannt.")
        if issue.stream_index is None:
            return LanguageDetectionResult("", 0.0, False, (), "Untertitel besitzt keinen eindeutigen Streamindex.")
        text = self._extract_subtitle_text(issue.path, issue.stream_index)
        if self._abort_requested():
            return LanguageDetectionResult("", 0.0, False, (), "Spracherkennung abgebrochen.")
        return detect_text_language(text, min_probability=max(0.80, self.min_probability - 0.05))

    def _whisper_detector(self) -> FasterWhisperLanguageDetector:
        if self._whisper is None:
            source = self.model_path if self.use_local_model else self.model_name
            self._log(f"faster-whisper Modell '{source}' wird geladen …", "info")
            self._whisper = FasterWhisperLanguageDetector(
                model_name=self.model_name,
                model_path=self.model_path,
                use_local_model=self.use_local_model,
            )
        return self._whisper

    def _extract_audio_sample(self, path: str, stream_index: int, start: float, target: Path) -> bool:
        cmd = [
            str(getattr(self.tools, "ffmpeg", "ffmpeg")),
            "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{max(0.0, start):.3f}",
            "-i", str(path),
            "-map", f"0:{int(stream_index)}",
            "-t", str(self.sample_seconds),
            "-vn", "-sn", "-dn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            str(target),
        ]
        result = run_tool(cmd, worker=self.worker, abort_on_request=True, timeout_s=max(60, self.sample_seconds * 4))
        return result.returncode == 0 and target.is_file() and target.stat().st_size > 1024

    def _extract_subtitle_text(self, path: str, stream_index: int) -> str:
        with tempfile.TemporaryDirectory(prefix="dragon_sub_lang_") as tmp:
            target = Path(tmp) / "subtitle.srt"
            cmd = [
                str(getattr(self.tools, "ffmpeg", "ffmpeg")),
                "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(path),
                "-map", f"0:{int(stream_index)}",
                "-c:s", "srt", str(target),
            ]
            result = run_tool(cmd, worker=self.worker, abort_on_request=True, timeout_s=120)
            if result.returncode != 0 or not target.is_file():
                return ""
            return target.read_text(encoding="utf-8", errors="replace")[:250_000]

    def _probe_duration(self, path: str) -> float:
        cmd = [
            str(getattr(self.tools, "ffprobe", "ffprobe")),
            "-v", "error", "-show_entries", "format=duration", "-of", "json", str(path),
        ]
        result = run_tool(cmd, worker=self.worker, abort_on_request=True, timeout_s=60)
        if result.returncode != 0:
            return 0.0
        try:
            data = json.loads(result.stdout or "{}")
            return max(0.0, float((data.get("format") or {}).get("duration") or 0.0))
        except (TypeError, ValueError, json.JSONDecodeError):
            return 0.0

    def _abort_requested(self) -> bool:
        return bool(self.worker is not None and getattr(self.worker, "abort_requested", False))

    def _setting_int(self, key: str, default: int, *, minimum: int, maximum: int) -> int:
        try:
            value = int(self.settings.value(key, default, type=int))
        except (AttributeError, TypeError, ValueError):
            value = int(default)
        return max(minimum, min(maximum, value))

    def _setting_str(self, key: str, default: str) -> str:
        try:
            value = str(self.settings.value(key, default, type=str) or default).strip()
        except (AttributeError, TypeError):
            value = default
        return value or default

    def _setting_bool(self, key: str, default: bool) -> bool:
        try:
            return bool(self.settings.value(key, default, type=bool))
        except (AttributeError, TypeError, ValueError):
            return bool(default)

    def _log(self, message: str, level: str = "info") -> None:
        if callable(self.log):
            self.log(message, level)


def _sample_starts(duration: float, count: int, sample_seconds: int) -> list[float]:
    count = max(1, int(count))
    duration = max(0.0, float(duration or 0.0))
    sample_seconds = max(1, int(sample_seconds))
    if duration <= sample_seconds + 1:
        return [0.0]
    usable = max(0.0, duration - sample_seconds)
    if count == 1:
        return [usable * 0.5]
    left, right = 0.15, 0.85
    return [usable * (left + (right - left) * index / (count - 1)) for index in range(count)]


__all__ = ["MediaStreamLanguageService", "_sample_starts"]
