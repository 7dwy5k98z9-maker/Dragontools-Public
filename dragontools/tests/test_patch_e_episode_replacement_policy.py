from __future__ import annotations


def _service(*, mode="auto", ask=None, conflict_mode="skip", log=None):
    from dragontools.core.move_file_service import MoveFileService

    return MoveFileService(
        conflict_mode=conflict_mode,
        episode_replacement_mode=mode,
        confirm_episode_replacement=ask,
        log=log or (lambda *_args: None),
        wait=lambda: None,
        abort_immediately=lambda: False,
        journal=None,
    )


def _fixture(tmp_path, *, code="S01E03"):
    src_dir = tmp_path / "work"
    dst_dir = tmp_path / "Serien" / "Serie 1" / ("Specials" if code.startswith("S00") else "Staffel 01")
    src_dir.mkdir(parents=True)
    dst_dir.mkdir(parents=True)
    source = src_dir / f"Serie 1 - {code} - Neuer Titel.mp4"
    old = dst_dir / f"Serie 1 - {code} - Alter Titel.mkv"
    old_nfo = dst_dir / f"Serie 1 - {code} - Alter Titel.nfo"
    source.write_bytes(b"new")
    old.write_bytes(b"old")
    old_nfo.write_text("old-nfo", encoding="utf-8")
    return source, dst_dir, old, old_nfo


def test_default_setting_preserves_previous_automatic_replacement_behavior():
    from dragontools.core.settings_storage import DEFAULT_EPISODE_REPLACEMENT_MODE

    assert DEFAULT_EPISODE_REPLACEMENT_MODE == "auto"


def test_auto_replaces_identity_only_episode_and_old_artifacts(tmp_path):
    source, dst_dir, old, old_nfo = _fixture(tmp_path)

    ok, result = _service(mode="auto").move(source, dst_dir)

    assert ok is True
    assert not source.exists()
    assert not old.exists()
    assert not old_nfo.exists()
    assert (dst_dir / source.name).read_bytes() == b"new"
    assert result["episode_identity_replacement"] is True
    assert result["episode_identity_replacement_declined"] is False


def test_never_skips_identity_only_episode_without_touching_existing_files(tmp_path):
    source, dst_dir, old, old_nfo = _fixture(tmp_path)
    logs: list[str] = []

    ok, result = _service(mode="never", log=lambda msg, _level="info": logs.append(msg)).move(
        source, dst_dir
    )

    assert ok is False
    assert source.read_bytes() == b"new"
    assert old.read_bytes() == b"old"
    assert old_nfo.read_text(encoding="utf-8") == "old-nfo"
    assert not (dst_dir / source.name).exists()
    assert result["skipped_conflict"] is True
    assert result["episode_identity_replacement_declined"] is True
    assert any("SxxExx-Ersetzung deaktiviert" in line for line in logs)


def test_ask_can_confirm_identity_only_replacement_and_receives_precise_payload(tmp_path):
    source, dst_dir, old, _old_nfo = _fixture(tmp_path)
    prompts: list[dict] = []

    def approve(payload: dict) -> bool:
        prompts.append(payload)
        return True

    ok, result = _service(mode="ask", ask=approve).move(source, dst_dir)

    assert ok is True
    assert not old.exists()
    assert result["episode_identity_replacement"] is True
    assert len(prompts) == 1
    assert prompts[0]["type"] == "confirm_episode_replacement"
    assert prompts[0]["episode_label"] == "S01E03"
    assert prompts[0]["target_name"] == source.name
    assert prompts[0]["conflict_names"] == [old.name]


def test_ask_decline_skips_only_current_episode(tmp_path):
    source, dst_dir, old, old_nfo = _fixture(tmp_path)

    ok, result = _service(mode="ask", ask=lambda _payload: False).move(source, dst_dir)

    assert ok is False
    assert source.exists()
    assert old.exists()
    assert old_nfo.exists()
    assert result["episode_identity_replacement_declined"] is True


def test_episode_policy_does_not_override_same_stem_conflict_behavior(tmp_path):
    src_dir = tmp_path / "work"
    dst_dir = tmp_path / "target"
    src_dir.mkdir()
    dst_dir.mkdir()
    source = src_dir / "Serie 1 - S01E03 - Gleicher Titel.mkv"
    old = dst_dir / "Serie 1 - S01E03 - Gleicher Titel.mp4"
    source.write_bytes(b"new")
    old.write_bytes(b"old")

    ok, result = _service(mode="never", conflict_mode="skip").move(source, dst_dir)

    # This is a normal same-stem/container conflict, not an SxxExx-only match.
    # Patch E intentionally preserves the existing episode replacement behavior here.
    assert ok is True
    assert not old.exists()
    assert result["episode_identity_replacement_declined"] is False


def test_specials_s00_follow_same_replacement_policy(tmp_path):
    source, dst_dir, old, _old_nfo = _fixture(tmp_path, code="S00E02")

    ok, result = _service(mode="never").move(source, dst_dir)

    assert ok is False
    assert source.exists()
    assert old.exists()
    assert result["episode_identity_replacement_declined"] is True


def test_multi_episode_identity_remains_precise_with_policy(tmp_path):
    src_dir = tmp_path / "work"
    dst_dir = tmp_path / "target"
    src_dir.mkdir()
    dst_dir.mkdir()
    source = src_dir / "Serie - S01E03 - Einzelfolge.mkv"
    multi = dst_dir / "Serie - S01E03E04 - Doppelfolge.mkv"
    source.write_bytes(b"single")
    multi.write_bytes(b"multi")

    ok, result = _service(mode="never").move(source, dst_dir)

    assert ok is True
    assert multi.read_bytes() == b"multi"
    assert (dst_dir / source.name).read_bytes() == b"single"
    assert result["episode_identity_replacement"] is False


def test_move_journal_resume_preserves_episode_replacement_mode(tmp_path):
    from dragontools.core.move_journal import MoveJournal, build_move_resume_plan, read_active_move_journal

    source = str(tmp_path / "Serie - S01E03.mkv")
    journal = MoveJournal.start(
        files=[source],
        episode_replacement_mode="never",
        root=tmp_path,
    )
    journal.finish_run(status="incomplete", keep_active=True)

    data = read_active_move_journal(tmp_path)
    assert data is not None
    plan = build_move_resume_plan(data)
    assert plan["episode_replacement_mode"] == "never"
