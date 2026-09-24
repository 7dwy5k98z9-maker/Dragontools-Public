from __future__ import annotations

from contextlib import closing
from pathlib import Path
from types import SimpleNamespace

import pytest

from dragontools.core.bitmap_subtitle_ocr import (
    BitmapOcrCue,
    BitmapSubtitlePacket,
    finalize_ocr_report,
    load_ocr_report,
    merge_adjacent_duplicate_cues,
    parse_tesseract_tsv,
    write_pending_draft,
)
from dragontools.core.media_library_db import _connect, initialize_database
from dragontools.core.media_library_fix_queue import (
    ACTION_OCR_BITMAP_SUBTITLE,
    MediaLibraryFixIssue,
    discover_fix_issues,
)
from dragontools.worker.bitmap_subtitle_ocr_service import BitmapSubtitleOcrService


class _Settings:
    values = {
        "media_library/ocr_languages": "deu+eng",
        "media_library/ocr_min_confidence": 75,
    }

    def value(self, key, default=None, type=None):
        value = self.values.get(key, default)
        return type(value) if type is not None else value


class _Tools:
    ffmpeg = "ffmpeg"
    ffprobe = "ffprobe"
    tesseract = "tesseract"


def _issue(tmp_path: Path, codec: str = "hdmv_pgs_subtitle") -> MediaLibraryFixIssue:
    media = tmp_path / "Movie.mkv"
    media.write_bytes(b"mkv")
    return MediaLibraryFixIssue(
        media_id=1,
        path=str(media),
        title="Movie",
        item_type="movie",
        issue_type="bitmap_subtitle_ocr",
        action=ACTION_OCR_BITMAP_SUBTITLE,
        problem="OCR",
        action_label="OCR-Entwurf erzeugen",
        stream_id=7,
        stream_index=2,
        stream_type="subtitle",
        stream_ordinal=1,
        codec=codec,
        language="und",
        forced=True,
        duration_s=1200.0,
    )


def test_tesseract_tsv_parser_preserves_lines_and_weighted_confidence() -> None:
    tsv = (
        "level\tpage_num\tblock_num\tpar_num\tline_num\tword_num\tleft\ttop\twidth\theight\tconf\ttext\n"
        "5\t1\t1\t1\t1\t1\t0\t0\t10\t10\t95\tHallo\n"
        "5\t1\t1\t1\t1\t2\t0\t0\t10\t10\t85\tWelt\n"
        "5\t1\t1\t1\t2\t1\t0\t0\t10\t10\t90\tWeiter\n"
    )
    text, confidence = parse_tesseract_tsv(tsv)
    assert text == "Hallo Welt\nWeiter"
    assert 0.89 < confidence < 0.91


def test_duplicate_ocr_cues_merge_but_keep_lowest_confidence() -> None:
    cues = merge_adjacent_duplicate_cues([
        BitmapOcrCue(1, 1.0, 2.0, "Hallo Welt", 0.96, False),
        BitmapOcrCue(2, 2.2, 3.0, "Hallo   Welt", 0.70, True),
        BitmapOcrCue(3, 5.0, 6.0, "Andere Zeile", 0.92, False),
    ])
    assert len(cues) == 2
    assert cues[0].end_s == 3.0
    assert cues[0].confidence == 0.70
    assert cues[0].uncertain is True


def test_pending_draft_requires_review_and_finalization_never_overwrites_existing_srt(tmp_path: Path) -> None:
    media = tmp_path / "Movie.mkv"
    media.write_bytes(b"mkv")
    existing = tmp_path / "Movie.de.forced.srt"
    existing.write_text("existing", encoding="utf-8")
    draft = write_pending_draft(
        media_path=media,
        stream_ordinal=2,
        stream_index=4,
        codec="hdmv_pgs_subtitle",
        source_language="deu",
        forced=True,
        cues=[BitmapOcrCue(1, 1.0, 2.5, "Hallo Welt", 0.93, False)],
        min_confidence=0.75,
    )
    assert Path(draft.draft_path).suffix == ".pending"
    assert Path(draft.report_path).suffix == ".pending"
    report = load_ocr_report(draft.report_path)
    assert report["detected_language"] == "de"
    final = finalize_ocr_report(draft.report_path, ["Hallo Welt!"])
    assert final.name == "Movie.de.forced.1.srt"
    assert final.read_text(encoding="utf-8").endswith("Hallo Welt!\n")
    assert existing.read_text(encoding="utf-8") == "existing"
    assert not Path(draft.draft_path).exists()
    assert not Path(draft.report_path).exists()


@pytest.mark.parametrize("codec", ["hdmv_pgs_subtitle", "dvd_subtitle", "vobsub"])
def test_fix_discovery_offers_bitmap_ocr_as_separate_category(tmp_path: Path, codec: str) -> None:
    db = initialize_database(tmp_path / "library.sqlite3")
    media = tmp_path / "Movie.mkv"
    with closing(_connect(db)) as conn, conn:
        cursor = conn.execute(
            """
            INSERT INTO media_items(item_type,title,path,filename,duration_s,width,height,video_codec,
                nfo_status,trickplay_status,analysis_status,exists_flag,active,created_at,updated_at)
            VALUES('movie','Movie',?,'Movie.mkv',1200,1920,1080,'hevc','present','present','ok',1,1,'now','now')
            """,
            (str(media),),
        )
        conn.execute(
            "INSERT INTO media_streams(media_id,stream_type,stream_index,codec,language,forced,title) "
            "VALUES(?, 'Subtitle', 2, ?, 'deu', 1, 'Deutsch PGS')",
            (int(cursor.lastrowid), codec),
        )
    result = discover_fix_issues(db, categories={"ocr"})
    assert len(result.issues) == 1
    assert result.issues[0].action == ACTION_OCR_BITMAP_SUBTITLE
    assert result.issues[0].codec == codec


def test_stream_language_category_does_not_offer_bitmap_language_guess_without_ocr(tmp_path: Path) -> None:
    db = initialize_database(tmp_path / "library.sqlite3")
    media = tmp_path / "Movie.mkv"
    with closing(_connect(db)) as conn, conn:
        cursor = conn.execute(
            """
            INSERT INTO media_items(item_type,title,path,filename,duration_s,width,height,video_codec,
                nfo_status,trickplay_status,analysis_status,exists_flag,active,created_at,updated_at)
            VALUES('movie','Movie',?,'Movie.mkv',1200,1920,1080,'hevc','present','present','ok',1,1,'now','now')
            """,
            (str(media),),
        )
        conn.execute(
            "INSERT INTO media_streams(media_id,stream_type,stream_index,codec,language,title) "
            "VALUES(?, 'Subtitle', 2, 'hdmv_pgs_subtitle', 'und', '')",
            (int(cursor.lastrowid),),
        )
    result = discover_fix_issues(db, categories={"streams"})
    assert result.issues == ()


def test_ocr_service_creates_review_draft_without_real_ffmpeg_or_tesseract(monkeypatch, tmp_path: Path) -> None:
    issue = _issue(tmp_path)
    service = BitmapSubtitleOcrService(settings=_Settings(), tools=_Tools())
    monkeypatch.setattr("dragontools.worker.bitmap_subtitle_ocr_service.tool_available", lambda _tool: True)
    monkeypatch.setattr(
        service,
        "_probe_packets",
        lambda *_args: [BitmapSubtitlePacket(1.0, 2.0), BitmapSubtitlePacket(3.0, 4.0)],
    )
    monkeypatch.setattr(service, "_validate_tesseract_languages", lambda _tool: None)

    def _render(_issue, _packet, target, _ffmpeg):
        target.write_bytes(b"png" * 100)
        return True

    monkeypatch.setattr(service, "_render_subtitle_image", _render)
    answers = iter([("Hallo Welt", 0.96), ("Ich bin hier", 0.60)])
    monkeypatch.setattr(service, "_ocr_image", lambda *_args: next(answers))
    draft = service.create_draft(issue)
    assert draft.cue_count == 2
    assert draft.uncertain_count == 1
    assert Path(draft.draft_path).exists()
    assert Path(draft.report_path).exists()


def test_ocr_service_rejects_non_mkv_source(tmp_path: Path) -> None:
    issue = _issue(tmp_path)
    mp4 = tmp_path / "Movie.mp4"
    mp4.write_bytes(b"mp4")
    issue = MediaLibraryFixIssue(**{**issue.__dict__, "path": str(mp4)})
    service = BitmapSubtitleOcrService(settings=_Settings(), tools=_Tools())
    with pytest.raises(RuntimeError, match="nur für MKV"):
        service.create_draft(issue)


def test_patch_j_ui_and_tool_configuration_are_exposed() -> None:
    root = Path(__file__).resolve().parents[1]
    tab = (root / "gui" / "media_library_fix_tab.py").read_text(encoding="utf-8")
    controller = (root / "gui" / "media_library_fix_controller.py").read_text(encoding="utf-8")
    tools = (root / "core" / "tool_paths.py").read_text(encoding="utf-8")
    assert "fix_ocr_cb" in tab
    assert "fix_ocr_languages_edit" in tab
    assert "fix_review_ocr_btn" in tab
    assert 'categories.add("ocr")' in controller
    assert "BitmapSubtitleOcrReviewDialog" in controller
    assert "def tesseract" in tools
