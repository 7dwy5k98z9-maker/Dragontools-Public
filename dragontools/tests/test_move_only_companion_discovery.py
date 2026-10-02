from pathlib import Path

from dragontools.core.move_companion_discovery import (
    discover_move_companions,
    merge_discovered_move_companions,
)


def test_move_only_discovers_matching_sidecars_nfo_and_trickplay(tmp_path: Path) -> None:
    video = tmp_path / "Episode 01.mkv"
    video.write_bytes(b"video")
    expected = [
        tmp_path / "Episode 01.de.srt",
        tmp_path / "Episode 01.de.forced.sup",
        tmp_path / "Episode 01.ass",
        tmp_path / "Episode 01.nfo",
        tmp_path / "Episode 01.trickplay",
    ]
    for path in expected[:-1]:
        path.write_text("x", encoding="utf-8")
    expected[-1].mkdir()
    (expected[-1] / "00001.jpg").write_bytes(b"jpg")

    # Must not steal companions belonging to neighbouring media or generic files.
    (tmp_path / "Episode 010.de.srt").write_text("wrong", encoding="utf-8")
    (tmp_path / "movie.nfo").write_text("generic", encoding="utf-8")
    (tmp_path / "Episode 01.txt").write_text("not a playback sidecar", encoding="utf-8")

    found = {Path(value).name for value in discover_move_companions(video)}
    assert found == {path.name for path in expected}


def test_move_only_merges_with_existing_artifact_sidecars_without_duplicates(tmp_path: Path) -> None:
    video = tmp_path / "Film.mkv"
    subtitle = tmp_path / "Film.de.srt"
    generated = tmp_path / "Film.generated.srt"
    video.write_bytes(b"video")
    subtitle.write_text("sub", encoding="utf-8")
    generated.write_text("generated", encoding="utf-8")

    merged = merge_discovered_move_companions(
        [str(video)],
        {str(video): [str(generated), str(subtitle)]},
    )
    assert merged[str(video)] == [str(generated), str(subtitle)]
