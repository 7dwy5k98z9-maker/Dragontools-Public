from __future__ import annotations


def test_move_report_groups_by_target_and_counts_conflict_actions():
    from dragontools.core.move_report import build_move_target_summary

    groups = build_move_target_summary(
        [
            {
                "kind": "video",
                "name": "film1.mkv",
                "target_dir": "D:/Anime/Serie",
                "ok": True,
                "conflict": True,
                "deleted_existing": True,
            },
            {
                "kind": "video",
                "name": "film2.mkv",
                "target_dir": "D:/Anime/Serie",
                "ok": False,
                "conflict": True,
                "skipped_conflict": True,
            },
            {
                "kind": "sidecar",
                "name": "film1.de.srt",
                "target_dir": "D:/Anime/Serie",
                "ok": True,
            },
            {
                "kind": "video",
                "name": "movie.mkv",
                "target_dir": "D:/Filme/Movie",
                "ok": True,
                "conflict": True,
                "replaced_existing": True,
            },
        ]
    )

    assert len(groups) == 2
    anime = groups[0]
    assert anime["target_dir"] == "D:/Anime/Serie"
    assert anime["planned"] == 2
    assert anime["moved"] == 1
    assert anime["errors"] == 1
    assert anime["deleted_existing"] == 1
    assert anime["skipped_conflict"] == 1
    assert anime["sidecars_moved"] == 1

    film = groups[1]
    assert film["target_dir"] == "D:/Filme/Movie"
    assert film["planned"] == 1
    assert film["moved"] == 1
    assert film["replaced_existing"] == 1


def test_move_report_format_mentions_deleted_and_replaced_files():
    from dragontools.core.move_report import format_move_target_summary_lines

    lines = format_move_target_summary_lines(
        [
            {
                "kind": "video",
                "name": "a.mkv",
                "target_dir": "D:/Ziel",
                "ok": True,
                "conflict": True,
                "deleted_existing": True,
            },
            {
                "kind": "video",
                "name": "b.mkv",
                "target_dir": "D:/Ziel",
                "ok": True,
                "conflict": True,
                "replaced_existing": True,
            },
        ],
        move_ok=2,
        move_errors=0,
    )

    text = "\n".join(lines)
    assert "📦  Verschiebebericht" in text
    assert "🎯  Ziel: D:/Ziel" in text
    assert "Gelöschte/ersetzte Dateien: 2" in text
    assert "1 gelöscht" in text
    assert "1 ersetzt" in text


def test_move_report_counts_multiple_removed_target_versions():
    from dragontools.core.move_report import format_move_target_summary_lines

    lines = format_move_target_summary_lines(
        [
            {
                "kind": "video",
                "name": "film.mkv",
                "target_dir": "D:/Ziel",
                "ok": True,
                "conflict": True,
                "deleted_existing": True,
                "deleted_existing_count": 2,
            },
        ],
        move_ok=1,
        move_errors=0,
    )

    text = "\n".join(lines)
    assert "Gelöschte/ersetzte Dateien: 2" in text
    assert "2 gelöscht" in text


def test_move_report_groups_sidecars_by_type_and_conflict_action():
    from dragontools.core.move_report import format_move_target_summary_lines

    lines = format_move_target_summary_lines(
        [
            {
                "kind": "video",
                "name": "film.mkv",
                "target_dir": "D:/Ziel",
                "ok": True,
            },
            {
                "kind": "sidecar",
                "sidecar_type": "subtitle",
                "name": "film.de.srt",
                "target_dir": "D:/Ziel",
                "ok": True,
            },
            {
                "kind": "sidecar",
                "sidecar_type": "nfo",
                "name": "movie.nfo",
                "target_dir": "D:/Ziel",
                "ok": False,
                "conflict": True,
                "skipped_conflict": True,
            },
            {
                "kind": "sidecar",
                "sidecar_type": "trickplay",
                "name": "film.trickplay",
                "target_dir": "D:/Ziel",
                "ok": True,
                "conflict": True,
                "backed_up_existing": True,
            },
        ],
        move_ok=1,
        move_errors=0,
    )

    text = "\n".join(lines)
    assert "Untertitel: 1 OK | 0 Fehler" in text
    assert "NFO: 0 OK | 1 Fehler | 1 Konflikt(e) | 1 beibehalten" in text
    assert "Trickplay: 1 OK | 0 Fehler | 1 Konflikt(e) | 1 gesichert" in text
