# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path


def test_sidecar_commit_preserves_existing_user_file_as_backup(tmp_path):
    from dragontools.core.sidecar_transaction import SidecarCommitTransaction

    stage = tmp_path / "tmp"
    final = tmp_path / "final"
    stage.mkdir()
    final.mkdir()
    generated = stage / "Film.de.srt"
    generated.write_text("GENERATED", encoding="utf-8")
    existing = final / "Film.de.srt"
    existing.write_text("USER", encoding="utf-8")

    tx = SidecarCommitTransaction(
        [str(generated)],
        source_base=stage / "Film",
        destination_base=final / "Film",
    )
    paths = tx.commit()

    assert paths == [str(existing)]
    assert existing.read_text(encoding="utf-8") == "GENERATED"
    assert len(tx.backup_pairs) == 1
    _, backup = tx.backup_pairs[0]
    assert backup.read_text(encoding="utf-8") == "USER"


def test_sidecar_commit_rollback_restores_user_file_and_staging(tmp_path):
    from dragontools.core.sidecar_transaction import SidecarCommitTransaction

    stage = tmp_path / "tmp"
    final = tmp_path / "final"
    stage.mkdir()
    final.mkdir()
    generated = stage / "Film.de.srt"
    generated.write_text("GENERATED", encoding="utf-8")
    existing = final / "Film.de.srt"
    existing.write_text("USER", encoding="utf-8")

    tx = SidecarCommitTransaction(
        [str(generated)],
        source_base=stage / "Film",
        destination_base=final / "Film",
    )
    tx.commit()
    tx.rollback()

    assert generated.read_text(encoding="utf-8") == "GENERATED"
    assert existing.read_text(encoding="utf-8") == "USER"
    assert not any(final.glob("*.dragontools_backup*"))
