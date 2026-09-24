from __future__ import annotations

from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.language_detection import (
    LanguageDetectionResult,
    LanguageEvidence,
    combine_language_evidence,
    detect_text_language,
)
from dragontools.core.media_library_db import _connect, initialize_database
from dragontools.core.media_library_fix_queue import (
    ACTION_DETECT_STREAM_LANGUAGE,
    ACTION_FIX_TRACK_TITLE,
    MediaLibraryFixIssue,
    discover_fix_issues,
)
from dragontools.core.mkv_track_metadata import apply_mkv_track_metadata
from dragontools.core.track_titles import build_track_title, track_title_is_generic
from dragontools.worker.media_stream_language_service import (
    MediaStreamLanguageService,
    _sample_starts,
)


class _Settings:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        return type(value) if type is not None else value


class _Tools:
    ffmpeg = "ffmpeg"
    ffprobe = "ffprobe"
    mkvpropedit = "mkvpropedit"


def _stream_issue(tmp_path: Path, *, stream_type="audio", codec="eac3", suffix=".mkv") -> MediaLibraryFixIssue:
    path = tmp_path / f"Movie{suffix}"
    path.write_bytes(b"media")
    return MediaLibraryFixIssue(
        media_id=1,
        path=str(path),
        title="Movie",
        item_type="movie",
        issue_type="stream_language_unknown",
        action=ACTION_DETECT_STREAM_LANGUAGE,
        problem="Sprache unbekannt",
        action_label="Sprache erkennen",
        stream_id=11,
        stream_index=2,
        stream_type=stream_type,
        stream_ordinal=2,
        codec=codec,
        language="und",
        track_title="",
        forced=False,
        channels=6 if stream_type == "audio" else None,
        bitrate=640000 if stream_type == "audio" else None,
        duration_s=1200.0,
    )


def test_language_consensus_accepts_three_matching_high_confidence_samples() -> None:
    result = combine_language_evidence(
        [
            LanguageEvidence("de", 0.99),
            LanguageEvidence("deu", 0.96),
            LanguageEvidence("de", 0.98),
        ],
        min_probability=0.85,
    )
    assert result.accepted
    assert result.language == "de"
    assert result.probability == pytest.approx((0.99 + 0.96 + 0.98) / 3)


def test_language_consensus_rejects_conflicting_samples_even_with_majority() -> None:
    result = combine_language_evidence(
        [LanguageEvidence("de", 0.99), LanguageEvidence("en", 0.98), LanguageEvidence("de", 0.99)],
        min_probability=0.85,
    )
    assert result.language == "de"
    assert not result.accepted
    assert result.probability < 0.85


def test_text_language_detection_handles_german_and_japanese() -> None:
    german = detect_text_language(
        "Ich weiß nicht, was du hier machst. Wir müssen jetzt gehen und die anderen finden. "
        "Das ist nicht mein Problem, aber ich komme mit dir und wir sehen, was passiert."
    )
    japanese = detect_text_language("これは日本語の字幕です。あなたは何をしていますか？ 私たちは今ここを出ます。")
    assert german.accepted and german.language == "de"
    assert japanese.accepted and japanese.language == "ja"


def test_track_titles_are_only_considered_generic_when_safe_to_replace() -> None:
    assert track_title_is_generic("")
    assert track_title_is_generic("Track 2")
    assert not track_title_is_generic("Director Commentary")
    assert build_track_title(
        stream_type="audio", language="de", codec="eac3", channels=6, bitrate=640000
    ) == "Deutsch EAC3 5.1 640kbps"
    assert build_track_title(
        stream_type="subtitle", language="de", forced=True
    ) == "Deutsch Forced"


def test_sample_starts_cover_early_middle_and_late_content() -> None:
    starts = _sample_starts(1000.0, 3, 15)
    assert len(starts) == 3
    assert 100 < starts[0] < 200
    assert 450 < starts[1] < 550
    assert 800 < starts[2] < 900


def test_mkv_metadata_uses_typed_track_selector_and_both_language_tags(monkeypatch, tmp_path: Path) -> None:
    video = tmp_path / "Movie.mkv"
    video.write_bytes(b"mkv")
    captured = {}
    monkeypatch.setattr("dragontools.core.mkv_track_metadata.tool_available", lambda _path: True)

    def _run(cmd, **_kwargs):
        captured["cmd"] = cmd
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("dragontools.core.mkv_track_metadata.run_analysis_tool", _run)
    ok, _message = apply_mkv_track_metadata(
        str(video),
        stream_type="audio",
        ordinal=2,
        mkvpropedit_path="mkvpropedit",
        language="de",
        title="Deutsch EAC3 5.1 640kbps",
    )
    assert ok
    cmd = captured["cmd"]
    assert "track:a2" in cmd
    assert "language=deu" in cmd
    assert "language-ietf=de" in cmd
    assert "name=Deutsch EAC3 5.1 640kbps" in cmd


def test_stream_discovery_adds_unknown_language_and_missing_title_issues(tmp_path: Path) -> None:
    db = initialize_database(tmp_path / "library.sqlite3")
    video = tmp_path / "Movie.mkv"
    with closing(_connect(db)) as conn, conn:
        cursor = conn.execute(
            """
            INSERT INTO media_items(item_type,title,path,filename,duration_s,width,height,video_codec,
                nfo_status,trickplay_status,analysis_status,exists_flag,active,created_at,updated_at)
            VALUES('movie','Movie',?,'Movie.mkv',1200,1920,1080,'hevc','present','present','ok',1,1,'now','now')
            """,
            (str(video),),
        )
        media_id = int(cursor.lastrowid)
        conn.execute(
            "INSERT INTO media_streams(media_id,stream_type,stream_index,codec,language,channels,bitrate,title) "
            "VALUES(?, 'Audio', 1, 'eac3', 'und', 6, 640000, '')",
            (media_id,),
        )
        conn.execute(
            "INSERT INTO media_streams(media_id,stream_type,stream_index,codec,language,forced,title) "
            "VALUES(?, 'Subtitle', 2, 'subrip', 'deu', 1, '')",
            (media_id,),
        )

    result = discover_fix_issues(db, categories={"streams"})
    assert [issue.action for issue in result.issues] == [
        ACTION_DETECT_STREAM_LANGUAGE,
        ACTION_FIX_TRACK_TITLE,
    ]
    assert result.issues[0].stream_type == "audio"
    assert result.issues[0].stream_ordinal == 1
    assert result.issues[1].stream_type == "subtitle"
    assert result.issues[1].forced is True


def test_bitmap_subtitle_is_not_guessed_before_ocr_patch(tmp_path: Path) -> None:
    issue = _stream_issue(tmp_path, stream_type="subtitle", codec="hdmv_pgs_subtitle")
    service = MediaStreamLanguageService(settings=_Settings(), tools=_Tools())
    result = service.detect(issue)
    assert not result.accepted
    assert "Patch J" in result.reason


def test_mp4_detection_result_is_not_written_in_place(tmp_path: Path) -> None:
    issue = _stream_issue(tmp_path, suffix=".mp4")
    service = MediaStreamLanguageService(settings=_Settings(), tools=_Tools())
    result = LanguageDetectionResult(
        "de", 0.98, True, (LanguageEvidence("de", 0.98),), "Deutsch sicher erkannt."
    )
    ok, message = service.apply_detected_language(issue, result)
    assert not ok
    assert "nur für MKV" in message


def test_audio_detection_uses_multiple_whisper_samples_without_real_backend(monkeypatch, tmp_path: Path) -> None:
    issue = _stream_issue(tmp_path)
    service = MediaStreamLanguageService(settings=_Settings(), tools=_Tools())
    monkeypatch.setattr(
        "dragontools.worker.media_stream_language_service.FasterWhisperLanguageDetector.available",
        lambda: True,
    )

    class _Detector:
        def detect_file(self, audio_path: str):
            return LanguageEvidence("de", 0.97, audio_path)

    monkeypatch.setattr(service, "_whisper_detector", lambda: _Detector())

    def _extract(_path, _index, _start, target):
        target.write_bytes(b"0" * 2048)
        return True

    monkeypatch.setattr(service, "_extract_audio_sample", _extract)
    result = service.detect(issue)
    assert result.accepted
    assert result.language == "de"
    assert len(result.evidence) == 3


def test_patch_i_gui_exposes_stream_category_and_whisper_controls() -> None:
    root = Path(__file__).resolve().parents[1]
    tab = (root / "gui" / "media_library_fix_tab.py").read_text(encoding="utf-8")
    controller = (root / "gui" / "media_library_fix_controller.py").read_text(encoding="utf-8")
    assert "fix_streams_cb" in tab
    assert "fix_language_model_combo" in tab
    assert "fix_language_confidence_spin" in tab
    assert "fix_language_samples_spin" in tab
    assert 'categories.add("streams")' in controller
    assert "save_settings" in controller


def test_stream_discovery_does_not_offer_unwritable_mp4_header_fixes(tmp_path: Path) -> None:
    db = initialize_database(tmp_path / "library.sqlite3")
    video = tmp_path / "Movie.mp4"
    with closing(_connect(db)) as conn, conn:
        cursor = conn.execute(
            """
            INSERT INTO media_items(item_type,title,path,filename,duration_s,width,height,video_codec,
                nfo_status,trickplay_status,analysis_status,exists_flag,active,created_at,updated_at)
            VALUES('movie','Movie',?,'Movie.mp4',1200,1920,1080,'hevc','present','present','ok',1,1,'now','now')
            """,
            (str(video),),
        )
        conn.execute(
            "INSERT INTO media_streams(media_id,stream_type,stream_index,codec,language,channels,title) "
            "VALUES(?, 'Audio', 1, 'aac', 'und', 2, '')",
            (int(cursor.lastrowid),),
        )
    result = discover_fix_issues(db, categories={"streams"})
    assert result.issues == ()


def test_fix_service_uses_detection_then_refreshes_library_snapshot(monkeypatch, tmp_path: Path) -> None:
    from dragontools.worker.media_library_fix_service import MediaLibraryFixService

    issue = _stream_issue(tmp_path)
    service = MediaLibraryFixService(
        db_path=str(tmp_path / "library.sqlite3"),
        settings=_Settings(),
        tools=_Tools(),
    )
    detected = LanguageDetectionResult(
        "de", 0.97, True, (LanguageEvidence("de", 0.97),), "Deutsch mit 97.0% Konsens."
    )
    monkeypatch.setattr(service._language_service, "detect", lambda _issue: detected)
    monkeypatch.setattr(
        service._language_service,
        "apply_detected_language",
        lambda _issue, _result: (True, "Track-Metadaten wurden aktualisiert."),
    )
    refreshed = []
    monkeypatch.setattr(
        "dragontools.worker.media_library_fix_service.record_media_file",
        lambda db_path, path, tools=None: refreshed.append((db_path, path, tools)),
    )
    outcome = service.execute(issue)
    assert outcome.status == "success"
    assert refreshed == [(str(tmp_path / "library.sqlite3"), issue.path, service.tools)]


def test_fix_service_keeps_low_confidence_detection_as_skipped(monkeypatch, tmp_path: Path) -> None:
    from dragontools.worker.media_library_fix_service import MediaLibraryFixService

    issue = _stream_issue(tmp_path)
    service = MediaLibraryFixService(
        db_path=str(tmp_path / "library.sqlite3"),
        settings=_Settings(),
        tools=_Tools(),
    )
    monkeypatch.setattr(
        service._language_service,
        "detect",
        lambda _issue: LanguageDetectionResult("de", 0.60, False, (), "Zu unsicher."),
    )
    outcome = service.execute(issue)
    assert outcome.status == "skipped"
    assert outcome.message == "Zu unsicher."
