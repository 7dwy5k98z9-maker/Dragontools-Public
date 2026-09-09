from __future__ import annotations

from dragontools.core.run_summary import build_run_summary


def test_run_summary_counts_ok_errors_and_skipped(tmp_path):
    out = tmp_path / "film_H265.mkv"
    out.write_bytes(b"x" * 2048)

    summary = build_run_summary(
        [
            {"input_path": str(tmp_path / "film.mkv"), "output_path": str(out), "status": "ok"},
            {"input_path": str(tmp_path / "kaputt.mkv"), "status": "error"},
            {"input_path": str(tmp_path / "skip.mkv"), "status": "skipped"},
        ],
        total_before=10_000,
        total_after=2_000,
        move_ok=1,
        move_errors=2,
        archived=3,
    )

    assert summary["total"] == 3
    assert summary["ok"] == 1
    assert summary["errors"] == 1
    assert summary["skipped"] == 1
    assert summary["saved_bytes"] == 8_000
    assert summary["move_ok"] == 1
    assert summary["move_errors"] == 2
    assert summary["archived"] == 3
    assert summary["failed_inputs"] == [str(tmp_path / "kaputt.mkv")]


def test_run_summary_maps_emoji_statuses():
    summary = build_run_summary(
        [
            {"input_path": "a.mkv", "status": "✅"},
            {"input_path": "b.mkv", "status": "❌"},
            {"input_path": "c.mkv", "status": "⏭️"},
            {"input_path": "d.mkv", "status": "⚠️"},
        ]
    )

    assert [row["status"] for row in summary["rows"]] == ["ok", "error", "skipped", "error"]
    assert summary["has_failures"] is True


def test_run_summary_preserves_failure_report_details(tmp_path):
    report = tmp_path / "ErrorReports" / "film_error.txt"
    summary = build_run_summary(
        [
            {
                "input_path": str(tmp_path / "film.mkv"),
                "status": "error",
                "message": "Verify fehlgeschlagen",
                "error_report": str(report),
                "pipeline": "standard",
                "container": "mkv",
                "strategy": "standard",
            }
        ]
    )

    row = summary["rows"][0]
    assert row["message"] == "Verify fehlgeschlagen"
    assert row["error_report"] == str(report)
    assert row["pipeline"] == "standard"
    assert row["container"] == "mkv"


def test_run_summary_formats_postprocess_and_sidecar_details(tmp_path):
    out = tmp_path / "film.mkv"
    out.write_bytes(b"x")
    nfo = tmp_path / "film.nfo"
    trickplay = tmp_path / "film.trickplay"

    summary = build_run_summary(
        [
            {
                "input_path": str(tmp_path / "film_source.mkv"),
                "output_path": str(out),
                "status": "ok",
                "sidecars": [str(tmp_path / "film.de.srt"), str(nfo), str(trickplay)],
                "postprocess": [
                    {"kind": "nfo", "status": "created", "path": str(nfo)},
                    {"kind": "trickplay", "status": "skipped", "path": str(trickplay)},
                ],
            }
        ]
    )

    row = summary["rows"][0]
    assert row["sidecar_label"] == "Untertitel 1 | NFO 1 | Trickplay 1"
    assert "NFO erstellt" in row["postprocess_label"]
    assert "Trickplay beibehalten" in row["postprocess_label"]
    assert "NFO erstellt: 1" in summary["postprocess_summary_label"]
