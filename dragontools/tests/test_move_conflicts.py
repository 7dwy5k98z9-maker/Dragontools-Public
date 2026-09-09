from __future__ import annotations


def test_find_target_conflicts_matches_same_video_stem_with_other_extension(tmp_path):
    from dragontools.core.move_conflicts import find_target_conflicts

    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    src = src_dir / "Film.mkv"
    old = dst_dir / "Film.mp4"
    src.write_bytes(b"new")
    old.write_bytes(b"old")

    conflicts = find_target_conflicts(dst_dir / "Film.mkv", src)

    assert conflicts == [old]


def test_find_target_conflicts_includes_exact_and_other_video_extension(tmp_path):
    from dragontools.core.move_conflicts import find_target_conflicts

    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    src = src_dir / "Film.mkv"
    exact = dst_dir / "Film.mkv"
    old = dst_dir / "Film.mp4"
    src.write_bytes(b"new")
    exact.write_bytes(b"old mkv")
    old.write_bytes(b"old mp4")

    conflicts = find_target_conflicts(dst_dir / "Film.mkv", src)

    assert set(conflicts) == {exact, old}


def test_find_target_conflicts_does_not_delete_non_video_by_same_stem(tmp_path):
    from dragontools.core.move_conflicts import find_target_conflicts

    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    src = src_dir / "Film.mkv"
    cover = dst_dir / "Film.jpg"
    nfo = dst_dir / "Film.nfo"
    src.write_bytes(b"new")
    cover.write_bytes(b"cover")
    nfo.write_text("metadata", encoding="utf-8")

    conflicts = find_target_conflicts(dst_dir / "Film.mkv", src)

    assert conflicts == []


def test_find_target_conflicts_uses_exact_name_for_non_video_files(tmp_path):
    from dragontools.core.move_conflicts import find_target_conflicts

    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    src = src_dir / "Film.de.srt"
    exact = dst_dir / "Film.de.srt"
    other_suffix = dst_dir / "Film.de.ass"
    src.write_text("new", encoding="utf-8")
    exact.write_text("old", encoding="utf-8")
    other_suffix.write_text("ass", encoding="utf-8")

    conflicts = find_target_conflicts(dst_dir / "Film.de.srt", src)

    assert conflicts == [exact]


def test_find_target_conflicts_matches_same_episode_with_different_title(tmp_path):
    from dragontools.core.move_conflicts import find_episode_identity_conflicts, find_target_conflicts

    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst" / "Serie 1" / "Staffel 01"
    src_dir.mkdir()
    dst_dir.mkdir(parents=True)
    src = src_dir / "Serie 1 - S01E03 - Der Testfall 1.mp4"
    old = dst_dir / "Serie 1 - S01E03 - Testfall 1.mkv"
    src.write_bytes(b"new")
    old.write_bytes(b"old")

    target = dst_dir / src.name

    assert find_episode_identity_conflicts(target, src) == [old]
    assert find_target_conflicts(target, src) == [old]


def test_find_target_conflicts_matches_same_episode_when_container_changes_back(tmp_path):
    from dragontools.core.move_conflicts import find_target_conflicts

    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst" / "Serie 1" / "Staffel 01"
    src_dir.mkdir()
    dst_dir.mkdir(parents=True)
    src = src_dir / "Serie 1 - S01E03 - Testfall 1.mkv"
    old = dst_dir / "Serie 1 - S01E03 - Der Testfall 1.mp4"
    src.write_bytes(b"new")
    old.write_bytes(b"old")

    conflicts = find_target_conflicts(dst_dir / src.name, src)

    assert conflicts == [old]


def test_episode_identity_conflicts_keep_multi_episode_identity_precise(tmp_path):
    from dragontools.core.move_conflicts import find_target_conflicts

    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst" / "Serie 1" / "Staffel 01"
    src_dir.mkdir()
    dst_dir.mkdir(parents=True)
    src = src_dir / "Serie 1 - S01E03 - Einzelfolge.mkv"
    old_multi = dst_dir / "Serie 1 - S01E03E04 - Doppelfolge.mkv"
    src.write_bytes(b"new")
    old_multi.write_bytes(b"old")

    conflicts = find_target_conflicts(dst_dir / src.name, src)

    assert conflicts == []


def test_resolve_rename_path_uses_free_video_stem(tmp_path):
    from dragontools.core.move_conflicts import resolve_rename_path

    src_dir = tmp_path / "src"
    dst_dir = tmp_path / "dst"
    src_dir.mkdir()
    dst_dir.mkdir()
    src = src_dir / "Film.mkv"
    src.write_bytes(b"new")
    (dst_dir / "Film.mp4").write_bytes(b"old")
    (dst_dir / "Film_01.avi").write_bytes(b"old")

    candidate = resolve_rename_path(dst_dir / "Film.mkv", src)

    assert candidate == dst_dir / "Film_02.mkv"


def test_episode_replacement_artifacts_follow_sxxexx_for_nfo_and_trickplay(tmp_path):
    from dragontools.core.move_conflicts import find_episode_replacement_artifacts

    dst_dir = tmp_path / "Serie 1" / "Staffel 01"
    dst_dir.mkdir(parents=True)
    old_video = dst_dir / "Serie 1 - S01E03 - Alter Titel.mkv"
    target = dst_dir / "Serie 1 - S01E03 - Neuer Titel.mp4"
    old_video.write_bytes(b"old")
    old_nfo = dst_dir / "Serie 1 - S01E03 - Alter Titel.nfo"
    old_nfo.write_text("old-nfo", encoding="utf-8")
    old_trickplay = dst_dir / "Serie 1 - S01E03 - Alter Titel.trickplay"
    old_trickplay.mkdir()
    same_episode_other_name = dst_dir / "Serie 1 - S01E03 - Noch Aelter.nfo"
    same_episode_other_name.write_text("stale", encoding="utf-8")
    other_episode_nfo = dst_dir / "Serie 1 - S01E04 - Andere Folge.nfo"
    other_episode_nfo.write_text("keep", encoding="utf-8")
    other_episode_trickplay = dst_dir / "Serie 1 - S01E04 - Andere Folge.trickplay"
    other_episode_trickplay.mkdir()

    found = find_episode_replacement_artifacts(target, [old_video])

    assert set(found) == {old_nfo, old_trickplay, same_episode_other_name}
    assert other_episode_nfo not in found
    assert other_episode_trickplay not in found


def test_episode_replacement_artifacts_keep_multi_episode_identity_precise(tmp_path):
    from dragontools.core.move_conflicts import find_episode_replacement_artifacts

    dst_dir = tmp_path / "Serie" / "Staffel 01"
    dst_dir.mkdir(parents=True)
    old_video = dst_dir / "Serie - S01E03 - Alt.mkv"
    old_video.write_bytes(b"old")
    single_nfo = dst_dir / "Serie - S01E03 - Alt.nfo"
    single_nfo.write_text("single", encoding="utf-8")
    multi_nfo = dst_dir / "Serie - S01E03E04 - Doppelfolge.nfo"
    multi_nfo.write_text("multi", encoding="utf-8")

    found = find_episode_replacement_artifacts(
        dst_dir / "Serie - S01E03 - Neu.mp4",
        [old_video],
    )

    assert single_nfo in found
    assert multi_nfo not in found
