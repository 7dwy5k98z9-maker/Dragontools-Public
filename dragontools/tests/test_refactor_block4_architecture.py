from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_block4_facades_stay_small_and_focused():
    limits = {
        "core/settings_backup.py": 80,
        "core/job_journal.py": 240,
        "core/rules_preview.py": 130,
        "gui/drop_path_extractor.py": 330,
    }
    for rel, limit in limits.items():
        lines = (ROOT / rel).read_text(encoding="utf-8").splitlines()
        assert len(lines) <= limit, f"{rel} ist wieder zu groß: {len(lines)} > {limit}"


def test_block4_split_modules_are_release_smoke_checked():
    from dragontools.core.release_validation_package import _SMOKE_MODULES

    checked = {path.as_posix() for path in _SMOKE_MODULES}
    expected = {
        "core/settings_backup_common.py",
        "core/settings_backup_crypto.py",
        "core/settings_backup_export.py",
        "core/settings_backup_restore.py",
        "core/job_journal_storage.py",
        "core/job_journal_resume.py",
        "core/rules_preview_common.py",
        "core/rules_preview_audio.py",
        "core/rules_preview_subtitles.py",
        "core/rules_preview_video.py",
        "gui/drop_path_files.py",
        "gui/drop_path_decode.py",
        "gui/drop_path_windows.py",
    }
    assert expected <= checked


def test_public_compatibility_imports_survive_block4():
    from dragontools.core.job_journal import JobJournal, build_resume_plan
    from dragontools.core.rules_preview import _build_target_video_preview, build_rules_preview
    from dragontools.core.settings_backup import export_backup, restore_backup
    from dragontools.gui.drop_path_extractor import (
        _extract_candidate_paths_from_text,
        _iter_video_files_in_folder,
    )

    assert callable(JobJournal.start)
    assert callable(build_resume_plan)
    assert callable(build_rules_preview)
    assert callable(_build_target_video_preview)
    assert callable(export_backup)
    assert callable(restore_backup)
    assert callable(_extract_candidate_paths_from_text)
    assert callable(_iter_video_files_in_folder)
