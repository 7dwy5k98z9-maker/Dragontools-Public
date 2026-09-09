from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def test_extract_does_not_overwrite_existing_file(monkeypatch, tmp_path):
    import dragontools.subtitle.extractor as module

    out = tmp_path / "film.de.srt"
    out.write_text("USER", encoding="utf-8")
    called = []
    monkeypatch.setattr(module, "run_tool", lambda *a, **k: called.append((a, k)))

    assert module.extract_with_ffmpeg("film.mkv", 2, str(out)) is False
    assert out.read_text(encoding="utf-8") == "USER"
    assert called == []


def test_extract_uses_shared_runner_and_worker(monkeypatch, tmp_path):
    import dragontools.subtitle.extractor as module

    out = tmp_path / "film.de.srt"
    worker = object()
    seen = {}

    def fake_run_tool(cmd, **kwargs):
        seen["cmd"] = cmd
        seen.update(kwargs)
        out.write_text("SUB", encoding="utf-8")
        return SimpleNamespace(ok=True, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module, "run_tool", fake_run_tool)
    assert module.extract_with_ffmpeg("film.mkv", 2, str(out), worker=worker) is True
    assert seen["worker"] is worker
    assert "-n" in seen["cmd"]


def test_ffmpeg_inject_does_not_overwrite_existing_file(monkeypatch, tmp_path):
    import dragontools.subtitle.injector as module

    out = tmp_path / "film_sub.mp4"
    out.write_text("USER", encoding="utf-8")
    called = []
    monkeypatch.setattr(module, "run_tool", lambda *a, **k: called.append((a, k)))

    assert module.inject_with_ffmpeg("film.mp4", "sub.srt", str(out)) is False
    assert out.read_text(encoding="utf-8") == "USER"
    assert called == []


def test_ffmpeg_inject_uses_shared_runner(monkeypatch, tmp_path):
    import dragontools.subtitle.injector as module

    out = tmp_path / "film_sub.mp4"
    seen = {}

    def fake_run_tool(cmd, **kwargs):
        seen["cmd"] = cmd
        seen.update(kwargs)
        out.write_bytes(b"video")
        return SimpleNamespace(ok=True, returncode=0, stdout="", stderr="")

    monkeypatch.setattr(module, "run_tool", fake_run_tool)
    assert module.inject_with_ffmpeg("film.mp4", "sub.srt", str(out), worker="worker") is True
    assert seen["worker"] == "worker"
    assert "-n" in seen["cmd"]
