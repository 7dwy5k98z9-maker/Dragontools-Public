from __future__ import annotations

from pathlib import Path


def test_trickplay_uses_jellyfin_default_folder_and_ffmpeg_tile_filter(tmp_path):
    from dragontools.worker.trickplay_service import (
        TrickplayGenerator,
        TrickplaySettings,
        trickplay_sprite_dir_for_video,
    )

    video = tmp_path / "Film.mkv"
    video.write_bytes(b"video")
    settings = TrickplaySettings(enabled=True)
    generator = TrickplayGenerator(ffmpeg_path="ffmpeg", log=lambda _msg: None)

    cmd = generator._build_ffmpeg_cmd(
        video,
        trickplay_sprite_dir_for_video(video, settings) / "%d.jpg",
        settings,
        hwaccel="cuda",
    )

    assert trickplay_sprite_dir_for_video(video, settings) == tmp_path / "Film.trickplay" / "320 - 10x10"
    assert "-hwaccel" in cmd
    assert "cuda" in cmd
    assert "-hwaccel_output_format" not in cmd
    assert "fps=1/10,scale=320:-2,tile=10x10" in cmd
    assert "-q:v" in cmd
    assert "4" in cmd


def test_trickplay_existing_folder_is_returned_when_only_missing(tmp_path):
    from dragontools.worker.trickplay_service import TrickplayGenerator, TrickplaySettings, trickplay_sprite_dir_for_video

    video = tmp_path / "Film.mkv"
    video.write_bytes(b"video")
    settings = TrickplaySettings(enabled=True, only_missing=True)
    sprite_dir = trickplay_sprite_dir_for_video(video, settings)
    sprite_dir.mkdir(parents=True)
    (sprite_dir / "0.jpg").write_bytes(b"jpg")
    generator = TrickplayGenerator(ffmpeg_path="ffmpeg", log=lambda _msg: None)

    assert generator.generate(video, settings) == tmp_path / "Film.trickplay"


def test_trickplay_existing_root_allows_missing_sprite_variant(tmp_path, monkeypatch):
    from dragontools.worker import trickplay_service
    from dragontools.worker.trickplay_service import TrickplayGenerator, TrickplaySettings, trickplay_sprite_dir_for_video

    video = tmp_path / "Film.mkv"
    video.write_bytes(b"video")
    settings = TrickplaySettings(enabled=True, only_missing=True, width=640)
    (tmp_path / "Film.trickplay" / "320 - 10x10").mkdir(parents=True)

    def fake_run(self, _cmd):
        out = trickplay_sprite_dir_for_video(video, settings)
        partial = video.with_name(f"{video.stem}.trickplay.__partial__") / out.name
        partial.mkdir(parents=True, exist_ok=True)
        (partial / "0.jpg").write_bytes(b"jpg")
        return True

    monkeypatch.setattr(TrickplayGenerator, "_run", fake_run)
    generator = TrickplayGenerator(ffmpeg_path="ffmpeg", log=lambda _msg: None)

    assert generator.generate(video, settings) == tmp_path / "Film.trickplay"
    assert (tmp_path / "Film.trickplay" / "640 - 10x10" / "0.jpg").exists()


def test_trickplay_existing_root_can_be_backed_up(tmp_path, monkeypatch):
    from dragontools.worker.trickplay_service import TrickplayGenerator, TrickplaySettings

    video = tmp_path / "Film.mkv"
    video.write_bytes(b"video")
    existing = tmp_path / "Film.trickplay" / "320 - 10x10"
    existing.mkdir(parents=True)
    (existing / "0.jpg").write_bytes(b"old")
    settings = TrickplaySettings(enabled=True, conflict_mode="backup")

    def fake_run(self, _cmd):
        partial = video.with_name("Film.trickplay.__partial__") / "320 - 10x10"
        partial.mkdir(parents=True, exist_ok=True)
        (partial / "0.jpg").write_bytes(b"new")
        return True

    monkeypatch.setattr(TrickplayGenerator, "_run", fake_run)
    generator = TrickplayGenerator(ffmpeg_path="ffmpeg", log=lambda _msg: None)

    assert generator.generate(video, settings) == tmp_path / "Film.trickplay"
    assert (tmp_path / "Film.trickplay" / "320 - 10x10" / "0.jpg").read_bytes() == b"new"
    assert (tmp_path / "Film.trickplay.bak" / "320 - 10x10" / "0.jpg").read_bytes() == b"old"


def test_trickplay_can_read_source_but_write_for_output_video(tmp_path, monkeypatch):
    from dragontools.worker.trickplay_service import (
        TrickplayGenerator,
        TrickplaySettings,
        trickplay_sprite_dir_for_video,
    )

    source = tmp_path / "Quelle.mkv"
    output = tmp_path / "Fertig.mkv"
    source.write_bytes(b"source")
    output.write_bytes(b"output")
    settings = TrickplaySettings(enabled=True, source_mode="source")
    seen_cmds: list[list[str]] = []

    def fake_run(self, cmd):
        seen_cmds.append(list(cmd))
        partial = output.with_name("Fertig.trickplay.__partial__") / "320 - 10x10"
        partial.mkdir(parents=True, exist_ok=True)
        (partial / "0.jpg").write_bytes(b"jpg")
        return True

    monkeypatch.setattr(TrickplayGenerator, "_run", fake_run)
    generator = TrickplayGenerator(ffmpeg_path="ffmpeg", log=lambda _msg: None)

    assert generator.generate(source, settings, target_video_path=output) == tmp_path / "Fertig.trickplay"
    assert (tmp_path / "Fertig.trickplay" / "320 - 10x10" / "0.jpg").exists()
    assert str(source) in seen_cmds[0]
    assert trickplay_sprite_dir_for_video(output, settings).exists()


def test_trickplay_logs_hardware_mode(tmp_path, monkeypatch):
    from dragontools.worker.trickplay_service import (
        TrickplayGenerator,
        TrickplaySettings,
        trickplay_sprite_dir_for_video,
    )

    video = tmp_path / "Film.mkv"
    video.write_bytes(b"video")
    settings = TrickplaySettings(enabled=True, hwaccel="cuda")
    messages: list[str] = []

    def fake_run(self, _cmd):
        partial = video.with_name("Film.trickplay.__partial__") / trickplay_sprite_dir_for_video(video, settings).name
        partial.mkdir(parents=True, exist_ok=True)
        (partial / "0.jpg").write_bytes(b"jpg")
        return True

    monkeypatch.setattr(TrickplayGenerator, "_run", fake_run)
    generator = TrickplayGenerator(ffmpeg_path="ffmpeg", log=messages.append)

    assert generator.generate(video, settings) == tmp_path / "Film.trickplay"
    assert any("CUDA/NVDEC-Pfad startet" in msg for msg in messages)
    assert any("CUDA/NVDEC-Pfad erfolgreich" in msg for msg in messages)


def test_trickplay_logs_cpu_fallback_mode(tmp_path, monkeypatch):
    from dragontools.worker.trickplay_service import (
        TrickplayGenerator,
        TrickplaySettings,
        trickplay_sprite_dir_for_video,
    )

    video = tmp_path / "Film.mkv"
    video.write_bytes(b"video")
    settings = TrickplaySettings(enabled=True, hwaccel="cuda")
    calls = 0
    messages: list[str] = []

    def fake_run(self, _cmd):
        nonlocal calls
        calls += 1
        if calls <= 2:
            return False
        partial = video.with_name("Film.trickplay.__partial__") / trickplay_sprite_dir_for_video(video, settings).name
        partial.mkdir(parents=True, exist_ok=True)
        (partial / "0.jpg").write_bytes(b"jpg")
        return True

    monkeypatch.setattr(TrickplayGenerator, "_run", fake_run)
    generator = TrickplayGenerator(ffmpeg_path="ffmpeg", log=messages.append)

    assert generator.generate(video, settings) == tmp_path / "Film.trickplay"
    assert any("CUDA/NVDEC-Kompatibilitätsretry fehlgeschlagen" in msg for msg in messages)
    assert any("CPU-Fallback erfolgreich" in msg for msg in messages)


def test_trickplay_uses_cuda_download_retry_before_cpu_fallback(tmp_path, monkeypatch):
    from dragontools.worker.trickplay_service import (
        TrickplayGenerator,
        TrickplaySettings,
        trickplay_sprite_dir_for_video,
    )

    video = tmp_path / "Film.mkv"
    video.write_bytes(b"video")
    settings = TrickplaySettings(enabled=True, hwaccel="cuda")
    calls: list[list[str]] = []
    messages: list[str] = []

    def fake_run(self, cmd):
        calls.append(list(cmd))
        if len(calls) == 1:
            return False
        partial = video.with_name("Film.trickplay.__partial__") / trickplay_sprite_dir_for_video(video, settings).name
        partial.mkdir(parents=True, exist_ok=True)
        (partial / "0.jpg").write_bytes(b"jpg")
        return True

    monkeypatch.setattr(TrickplayGenerator, "_run", fake_run)
    generator = TrickplayGenerator(ffmpeg_path="ffmpeg", log=messages.append)

    assert generator.generate(video, settings) == tmp_path / "Film.trickplay"
    assert len(calls) == 2
    assert "-hwaccel_output_format" in calls[1]
    assert any("hwdownload,format=nv12" in part for part in calls[1])
    assert any("Kompatibilitätsretry" in msg for msg in messages)


def test_trickplay_overwrite_commit_failure_restores_previous_root(tmp_path, monkeypatch):
    from dragontools.core import move_transaction
    from dragontools.worker.trickplay_service import TrickplayGenerator, TrickplaySettings

    video = tmp_path / "Film.mkv"
    video.write_bytes(b"video")
    existing = tmp_path / "Film.trickplay" / "320 - 10x10"
    existing.mkdir(parents=True)
    (existing / "0.jpg").write_bytes(b"old")
    settings = TrickplaySettings(enabled=True, conflict_mode="overwrite")

    def fake_run(self, _cmd):
        partial = tmp_path / "Film.trickplay.__partial__" / "320 - 10x10"
        partial.mkdir(parents=True, exist_ok=True)
        (partial / "0.jpg").write_bytes(b"new")
        return True

    real_replace = move_transaction.os.replace

    def fail_partial_commit(src, dst):
        if ".__partial__" in str(src) and str(dst).endswith("Film.trickplay"):
            raise OSError("replace failed")
        return real_replace(src, dst)

    monkeypatch.setattr(TrickplayGenerator, "_run", fake_run)
    monkeypatch.setattr(move_transaction.os, "replace", fail_partial_commit)
    messages: list[str] = []
    generator = TrickplayGenerator(ffmpeg_path="ffmpeg", log=messages.append)

    assert generator.generate(video, settings) is None
    assert (existing / "0.jpg").read_bytes() == b"old"
    assert not (tmp_path / "Film.trickplay.__partial__").exists()
    assert not list(tmp_path.glob("Film.trickplay.bak*"))
    assert any("wiederhergestellt" in msg for msg in messages)


def test_trickplay_rollback_failure_keeps_old_backup(tmp_path, monkeypatch):
    from dragontools.core import move_transaction
    from dragontools.worker.trickplay_service import TrickplayGenerator, TrickplaySettings

    video = tmp_path / "Film.mkv"
    video.write_bytes(b"video")
    existing = tmp_path / "Film.trickplay" / "320 - 10x10"
    existing.mkdir(parents=True)
    (existing / "0.jpg").write_bytes(b"old")
    settings = TrickplaySettings(enabled=True, conflict_mode="overwrite")

    def fake_run(self, _cmd):
        partial = tmp_path / "Film.trickplay.__partial__" / "320 - 10x10"
        partial.mkdir(parents=True, exist_ok=True)
        (partial / "0.jpg").write_bytes(b"new")
        return True

    real_replace = move_transaction.os.replace
    calls = 0

    def fail_commit_and_rollback(src, dst):
        nonlocal calls
        calls += 1
        if calls in {2, 3}:
            raise OSError("commit failed" if calls == 2 else "rollback failed")
        return real_replace(src, dst)

    monkeypatch.setattr(TrickplayGenerator, "_run", fake_run)
    monkeypatch.setattr(move_transaction.os, "replace", fail_commit_and_rollback)
    messages: list[str] = []
    generator = TrickplayGenerator(ffmpeg_path="ffmpeg", log=messages.append)

    assert generator.generate(video, settings) is None
    backups = list(tmp_path.glob("Film.trickplay.bak*"))
    assert len(backups) == 1
    assert (backups[0] / "320 - 10x10" / "0.jpg").read_bytes() == b"old"
    assert any("Rollback" in msg and "Backup" in msg for msg in messages)


def test_trickplay_overwrite_keeps_backup_if_cleanup_fails(tmp_path, monkeypatch):
    from dragontools.core import move_transaction
    from dragontools.worker.trickplay_service import TrickplayGenerator, TrickplaySettings

    video = tmp_path / "Film.mkv"
    video.write_bytes(b"video")
    existing = tmp_path / "Film.trickplay" / "320 - 10x10"
    existing.mkdir(parents=True)
    (existing / "0.jpg").write_bytes(b"old")
    settings = TrickplaySettings(enabled=True, conflict_mode="overwrite")

    def fake_run(self, _cmd):
        partial = tmp_path / "Film.trickplay.__partial__" / "320 - 10x10"
        partial.mkdir(parents=True, exist_ok=True)
        (partial / "0.jpg").write_bytes(b"new")
        return True

    def fail_remove(_path):
        raise OSError("backup cleanup failed")

    monkeypatch.setattr(TrickplayGenerator, "_run", fake_run)
    monkeypatch.setattr(move_transaction, "remove_path", fail_remove)
    messages: list[str] = []
    generator = TrickplayGenerator(ffmpeg_path="ffmpeg", log=messages.append)

    assert generator.generate(video, settings) == tmp_path / "Film.trickplay"
    assert (tmp_path / "Film.trickplay" / "320 - 10x10" / "0.jpg").read_bytes() == b"new"
    backups = list(tmp_path.glob("Film.trickplay.bak*"))
    assert len(backups) == 1
    assert (backups[0] / "320 - 10x10" / "0.jpg").read_bytes() == b"old"
    assert any("Altbestand-Backup" in msg and "bleibt" in msg for msg in messages)


def test_trickplay_runner_has_runtime_timeout_and_drains_large_stderr(tmp_path):
    import sys
    from dragontools.worker.trickplay_service import TrickplayGenerator

    messages: list[str] = []
    generator = TrickplayGenerator(
        ffmpeg_path=sys.executable,
        log=messages.append,
        timeout_s=5,
    )

    assert generator._run(
        [sys.executable, "-c", "import sys; sys.stderr.write('x' * 2_000_000)"]
    ) is True

    timeout_generator = TrickplayGenerator(
        ffmpeg_path=sys.executable,
        log=messages.append,
        timeout_s=0.1,
    )
    assert timeout_generator._run(
        [sys.executable, "-c", "import time; time.sleep(2)"]
    ) is False
    assert any("Runtime-Timeout" in msg for msg in messages)


def test_trickplay_abort_after_file_request_still_stops_running_process():
    import sys
    import threading
    from types import SimpleNamespace
    from dragontools.worker.trickplay_service import TrickplayGenerator

    worker = SimpleNamespace(
        _lock=threading.RLock(),
        _current_process=None,
        _paused=False,
        abort_requested=True,
        abort_type="nach_datei",
    )
    messages: list[str] = []
    generator = TrickplayGenerator(
        ffmpeg_path=sys.executable,
        log=messages.append,
        worker=worker,
        timeout_s=5,
    )

    assert generator._run([sys.executable, "-c", "import time; time.sleep(5)"]) is False
    assert worker._current_process is None
    assert any("Trickplay abgebrochen" in msg for msg in messages)
