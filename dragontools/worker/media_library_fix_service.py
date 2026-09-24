from __future__ import annotations

from pathlib import Path
from typing import Callable

from ..core.media_library_fix_queue import (
    ACTION_GENERATE_NFO,
    ACTION_GENERATE_TRICKPLAY,
    ACTION_REANALYZE,
    ACTION_DETECT_STREAM_LANGUAGE,
    ACTION_FIX_TRACK_TITLE,
    ACTION_OCR_BITMAP_SUBTITLE,
    MediaLibraryFixIssue,
    MediaLibraryFixOutcome,
    refresh_sidecar_statuses,
)
from ..core.media_library_repository_items import record_media_file
from .postprocess_runner import PostProcessService
from .media_stream_language_service import MediaStreamLanguageService
from .bitmap_subtitle_ocr_service import BitmapSubtitleOcrService


LogFn = Callable[[str, str], None] | None


class MediaLibraryFixService:
    """Execute one media-library repair at a time.

    NFO/trickplay repairs remain create-only. Patch I additionally allows
    targeted MKV header metadata edits (language/title) after conservative
    language detection; media payloads are never re-encoded by this service.
    """

    def __init__(self, *, db_path: str, settings, tools, log: LogFn = None, worker=None) -> None:
        self.db_path = str(db_path)
        self.settings = settings
        self.tools = tools
        self.log = log
        self.worker = worker
        self._postprocess = PostProcessService(
            settings=settings,
            tools=tools,
            log=log,
            worker=worker,
        )
        self._language_service = MediaStreamLanguageService(
            settings=settings,
            tools=tools,
            log=log,
            worker=worker,
        )
        self._ocr_service = BitmapSubtitleOcrService(
            settings=settings,
            tools=tools,
            log=log,
            worker=worker,
        )

    def execute(self, issue: MediaLibraryFixIssue) -> MediaLibraryFixOutcome:
        if self.worker is not None and getattr(self.worker, "abort_requested", False):
            return self._outcome(issue, "skipped", "Fix Queue wurde abgebrochen.")
        path = Path(issue.path)
        if not path.is_file():
            return self._outcome(issue, "error", "Mediendatei wurde nicht gefunden.")
        try:
            if issue.action == ACTION_GENERATE_NFO:
                return self._generate_nfo(issue)
            if issue.action == ACTION_GENERATE_TRICKPLAY:
                return self._generate_trickplay(issue)
            if issue.action == ACTION_REANALYZE:
                return self._reanalyze(issue)
            if issue.action == ACTION_DETECT_STREAM_LANGUAGE:
                return self._detect_stream_language(issue)
            if issue.action == ACTION_FIX_TRACK_TITLE:
                return self._fix_track_title(issue)
            if issue.action == ACTION_OCR_BITMAP_SUBTITLE:
                return self._ocr_bitmap_subtitle(issue)
        except Exception as exc:
            self._log(f"Fix fehlgeschlagen für {path.name}: {exc}", "error")
            return self._outcome(issue, "error", str(exc))
        return self._outcome(issue, "error", f"Unbekannte Fix-Aktion: {issue.action}")

    def _generate_nfo(self, issue: MediaLibraryFixIssue) -> MediaLibraryFixOutcome:
        result = self._postprocess.create_nfo_only(media_path=issue.path)
        refresh_sidecar_statuses(self.db_path, issue.path)
        target = Path(issue.path).with_suffix(".nfo")
        movie_target = Path(issue.path).parent / "movie.nfo"
        if target.exists() or movie_target.exists():
            return self._outcome(issue, "success", "NFO ist vorhanden.")
        return self._outcome(issue, "error", self._result_message(result, "NFO konnte nicht erzeugt werden."))

    def _generate_trickplay(self, issue: MediaLibraryFixIssue) -> MediaLibraryFixOutcome:
        result = self._postprocess.create_trickplay_only(media_path=issue.path)
        refresh_sidecar_statuses(self.db_path, issue.path)
        root = Path(issue.path).with_name(f"{Path(issue.path).stem}.trickplay")
        if root.is_dir() and any(root.rglob("*.jpg")):
            return self._outcome(issue, "success", "Trickplay ist vorhanden.")
        return self._outcome(
            issue,
            "error",
            self._result_message(result, "Trickplay konnte nicht erzeugt werden."),
        )

    def _reanalyze(self, issue: MediaLibraryFixIssue) -> MediaLibraryFixOutcome:
        record_media_file(self.db_path, issue.path, tools=self.tools)
        return self._outcome(issue, "success", "Mediendaten wurden neu analysiert.")

    def _detect_stream_language(self, issue: MediaLibraryFixIssue) -> MediaLibraryFixOutcome:
        result = self._language_service.detect(issue)
        if self.worker is not None and getattr(self.worker, "abort_requested", False):
            return self._outcome(issue, "skipped", "Spracherkennung wurde abgebrochen.")
        if not result.accepted:
            return self._outcome(issue, "skipped", result.reason or "Sprache nicht sicher erkannt.")
        ok, message = self._language_service.apply_detected_language(issue, result)
        if not ok:
            return self._outcome(issue, "skipped", f"{result.reason} {message}".strip())
        record_media_file(self.db_path, issue.path, tools=self.tools)
        return self._outcome(issue, "success", f"{result.reason} {message}".strip())

    def _fix_track_title(self, issue: MediaLibraryFixIssue) -> MediaLibraryFixOutcome:
        ok, message = self._language_service.apply_track_title(issue)
        if not ok:
            return self._outcome(issue, "skipped", message)
        record_media_file(self.db_path, issue.path, tools=self.tools)
        return self._outcome(issue, "success", message)


    def _ocr_bitmap_subtitle(self, issue: MediaLibraryFixIssue) -> MediaLibraryFixOutcome:
        try:
            draft = self._ocr_service.create_draft(issue)
        except RuntimeError as exc:
            if self.worker is not None and getattr(self.worker, "abort_requested", False):
                return self._outcome(issue, "skipped", "Bitmap-OCR wurde abgebrochen.")
            raise
        return MediaLibraryFixOutcome(
            issue=issue,
            status="review",
            message=draft.message,
            artifact_path=draft.draft_path,
            report_path=draft.report_path,
        )

    @staticmethod
    def _result_message(result, fallback: str) -> str:
        for item in reversed(list(getattr(result, "items", []) or [])):
            message = str(item.get("message") or "").strip()
            if message:
                return message
        return fallback

    @staticmethod
    def _outcome(issue: MediaLibraryFixIssue, status: str, message: str) -> MediaLibraryFixOutcome:
        return MediaLibraryFixOutcome(issue=issue, status=status, message=message)

    def _log(self, message: str, level: str = "info") -> None:
        if callable(self.log):
            self.log(message, level)


__all__ = ["MediaLibraryFixService"]
