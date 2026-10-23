"""Recover unknown audio languages before conversion rules and contracts run."""
from dataclasses import replace
from pathlib import Path

from ..core.lang_codes import canonical_lang, lang_display
from ..core.media_library_fix_queue import ACTION_DETECT_STREAM_LANGUAGE, MediaLibraryFixIssue
from ..core.models import normalize_override_dict
from ..rules.audio_selection import unknown_audio_streams_without_priority_match
from .media_stream_language_service import MediaStreamLanguageService


class ConversionAudioLanguageRecovery:
    """Use read-only Whisper probes; only the conversion's analysis is updated.

    The existing output planners then reselect tracks using the normal rules
    and generate language/title metadata for the actual output codec. Source
    files, manual track mappings and existing known language tags are untouched.
    """

    def __init__(self, *, settings, tools, log, worker=None, detector=None, abort_check=None):
        self._settings = settings
        self._tools = tools
        self._log = log
        self._worker = worker
        self._detector = detector
        self._abort_check = abort_check or (lambda: False)
        self._detections = {}

    def prepare(self, media_info, file_override=None, *, rules=None):
        override = normalize_override_dict(file_override)
        if override.get("audio_mode") == "custom" or self._abort_check():
            return media_info
        # Audio-only MediaInfo fallbacks may have ordinal, not global ffmpeg
        # indices. Never map a language probe onto an untrusted stream index.
        if not getattr(media_info, "ffmpeg_stream_indices_trusted", True):
            return media_info
        candidates = unknown_audio_streams_without_priority_match(media_info.audio_streams, rules)
        if not candidates:
            return media_info
        self._log(
            f"Audio-Regeln: keine passende Sprache gefunden. Whisper prüft "
            f"{len(candidates)} unbekannte Audiospur(en) in {Path(media_info.path).name}.", "info",
        )
        updates = {}
        for stream in candidates:
            if self._abort_check():
                return media_info
            issue = MediaLibraryFixIssue(
                media_id=0, path=media_info.path, title=Path(media_info.path).name,
                item_type="file", issue_type="stream_language_unknown",
                action=ACTION_DETECT_STREAM_LANGUAGE, problem="Audio-Sprache unbekannt",
                action_label="Audio-Sprache erkennen", stream_type="audio",
                stream_index=stream.index,
                duration_s=stream.duration_s or media_info.duration_s,
            )
            key = (issue.path, issue.source_signature, stream.index)
            try:
                if key not in self._detections:
                    if self._detector is None:
                        self._detector = MediaStreamLanguageService(
                            settings=self._settings, tools=self._tools,
                            log=self._log, worker=self._worker,
                        )
                    # No apply_detected_language: source headers are not edited.
                    self._detections[key] = self._detector.detect(issue)
                result = self._detections[key]
            except Exception as exc:
                self._log(f"Audio Spur #{stream.index}: Spracherkennung fehlgeschlagen; "
                          f"Sprache bleibt unverändert ({exc}).", "warn")
                continue
            if self._abort_check():
                return media_info
            language = canonical_lang(result.language)
            if result.accepted and language not in {"", "und", "unk", "unknown", "undefined"}:
                updates[stream.index] = replace(stream, language=language)
                self._log(f"Audio Spur #{stream.index}: {lang_display(language)} bestätigt "
                          f"({result.probability * 100:.1f}%); Audio-Regeln werden neu angewendet.", "info")
            else:
                self._log(f"Audio Spur #{stream.index}: Sprache nicht sicher erkannt; "
                          f"Kennzeichnung bleibt unverändert. {result.reason}", "warn")
        if not updates:
            return media_info
        return replace(media_info, audio_streams=[
            updates.get(stream.index, stream) for stream in media_info.audio_streams
        ])
