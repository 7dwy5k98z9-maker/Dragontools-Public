from __future__ import annotations

from pathlib import Path

import pytest


def test_cleanup_removes_failed_output_and_sidecars(tmp_path):
    from dragontools.worker.cleanup_service import CleanupService

    output = tmp_path / "film_H265.mkv"
    sidecar = tmp_path / "film_H265.de.srt"
    related = tmp_path / "film_H265.de.sup"
    unrelated = tmp_path / "anderer_film.de.srt"
    for path in (output, sidecar, related, unrelated):
        path.write_bytes(b"x" * 2048)

    service = CleanupService(
        overwrite_original=False,
        temp_overwrite_dir=lambda base: base / "__temp_overwrite__",
        log=lambda *_: None,
    )

    service.cleanup_temp_artifacts(
        burn_sub_tmp=None,
        base_dir=tmp_path,
        output_path=str(output),
        sidecar_paths=[str(sidecar)],
        keep_output=False,
    )

    assert not output.exists()
    assert not sidecar.exists()
    # Nicht registrierte same-stem Sidecars koennen bereits vor dem Run existieren
    # und duerfen vom Failure-Cleanup niemals anhand ihres Namens geloescht werden.
    assert related.exists()
    assert unrelated.exists()


def test_cleanup_overwrite_removes_file_but_keeps_temp_dir_until_batch_end(tmp_path):
    from dragontools.worker.cleanup_service import CleanupService

    temp_dir = tmp_path / "__temp_overwrite__"
    output = temp_dir / "film.mkv"
    temp_dir.mkdir()
    output.write_bytes(b"x" * 2048)

    service = CleanupService(
        overwrite_original=True,
        temp_overwrite_dir=lambda base: base / "__temp_overwrite__",
        log=lambda *_: None,
    )

    service.cleanup_temp_artifacts(
        burn_sub_tmp=None,
        base_dir=tmp_path,
        output_path=str(output),
        keep_output=False,
    )

    assert not output.exists()
    assert temp_dir.exists()

    service.cleanup_empty_overwrite_dirs({tmp_path})

    assert not temp_dir.exists()


def test_cleanup_empty_overwrite_dirs_keeps_nonempty_parallel_dir_silent(tmp_path):
    from dragontools.worker.cleanup_service import CleanupService

    logs = []
    temp_dir = tmp_path / "__temp_overwrite__"
    temp_dir.mkdir()
    running_output = temp_dir / "noch_laufend.mkv"
    running_output.write_bytes(b"x" * 2048)

    service = CleanupService(
        overwrite_original=True,
        temp_overwrite_dir=lambda base: base / "__temp_overwrite__",
        log=lambda msg, level="info": logs.append((level, msg)),
    )

    service.cleanup_empty_overwrite_dirs({tmp_path})

    assert running_output.exists()
    assert temp_dir.exists()
    assert logs == []


def test_replace_same_path_rolls_original_back_on_failure(tmp_path, monkeypatch):
    import sys
    import types

    pyqt = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtcore.QSettings = object
    monkeypatch.setitem(sys.modules, "PyQt6", pyqt)
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", qtcore)

    import dragontools.worker.replace_service as module
    import dragontools.core.move_transaction as transaction_module
    from dragontools.worker.replace_service import ReplaceService

    source = tmp_path / "film.mkv"
    output = tmp_path / "__temp_overwrite__" / "film.mkv"
    output.parent.mkdir()
    source.write_bytes(b"original" * 200)
    output.write_bytes(b"encoded" * 200)

    monkeypatch.setattr(
        module,
        "validate_output_size_policy",
        lambda **_kwargs: (True, None),
    )

    real_replace = transaction_module.os.replace
    def fake_replace(src, dst):
        if Path(src) == output and Path(dst) == source:
            raise OSError("simulierter Replace-Fehler")
        return real_replace(src, dst)

    monkeypatch.setattr(transaction_module.os, "replace", fake_replace)
    logs = []
    service = ReplaceService(
        overwrite_original=True,
        log=lambda msg, level: logs.append((level, msg)),
        journal_root=tmp_path / "journals",
    )

    with pytest.raises(OSError):
        service.replace(input_path=str(source), output_path=str(output), container="mkv")

    assert source.exists()
    assert source.read_bytes().startswith(b"original")
    assert output.exists()
    assert any("Rollback: Original wiederhergestellt" in msg for _level, msg in logs)


def test_replace_size_policy_block_marks_file_as_not_replaced(tmp_path, monkeypatch):
    import sys
    import types

    pyqt = types.ModuleType("PyQt6")
    qtcore = types.ModuleType("PyQt6.QtCore")
    qtcore.QSettings = object
    monkeypatch.setitem(sys.modules, "PyQt6", pyqt)
    monkeypatch.setitem(sys.modules, "PyQt6.QtCore", qtcore)

    import dragontools.worker.replace_service as module
    from dragontools.worker.replace_service import ReplaceService

    source = tmp_path / "film.mkv"
    output = tmp_path / "__temp_overwrite__" / "film.mkv"
    archived = tmp_path / "Archiv" / "film.mkv"
    output.parent.mkdir()
    archived.parent.mkdir()
    source.write_bytes(b"original" * 100)
    output.write_bytes(b"encoded" * 200)
    archived.write_bytes(output.read_bytes())

    monkeypatch.setattr(
        module,
        "validate_output_size_policy",
        lambda **_kwargs: (False, archived),
    )

    service = ReplaceService(overwrite_original=True, log=lambda *_: None)

    result = service.replace(input_path=str(source), output_path=str(output), container="mkv")

    assert result == str(archived)
    assert source.exists()
    assert service.was_blocked(str(source))
    assert service.last_preserved_path == str(archived)
    assert "größer" in service.last_block_reason
    assert service.archiviert == 1
