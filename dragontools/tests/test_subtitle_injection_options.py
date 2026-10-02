from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from dragontools.subtitle.sidecar_matcher import find_injection_subtitle


def make_files(tmp_path, *names):
    for name in names:
        (tmp_path / name).write_bytes(b"fixture")


@pytest.mark.parametrize("suffix", ["de", "deu", "DEU"])
def test_same_basename_language_token(tmp_path, suffix):
    make_files(tmp_path, f"Serie.S01E02.{suffix}.srt", "Serie.S01E03.de.srt", "Serie.S01E02.eng.srt")
    assert find_injection_subtitle(tmp_path / "Serie.S01E02.mkv").name == f"Serie.S01E02.{suffix}.srt"


def test_episode_match_across_release_suffixes(tmp_path):
    make_files(tmp_path, "Serie.S01E02.subtitles.deu.srt", "Andere.S01E02.de.srt", "Serie.S02E02.de.srt")
    assert find_injection_subtitle(tmp_path / "Serie.S01E02.1080p.mkv").name == "Serie.S01E02.subtitles.deu.srt"


def test_english_selection_and_movie_basename(tmp_path):
    make_files(tmp_path, "Film.de.srt", "Film.en.ass")
    assert find_injection_subtitle(tmp_path / "Film.mkv", "eng").name == "Film.en.ass"


def test_ambiguous_files_are_not_arbitrarily_selected(tmp_path):
    make_files(tmp_path, "Serie.S01E02.de.srt", "Serie.S01E02.deu.ass")
    with pytest.raises(ValueError, match="Mehrere passende"):
        find_injection_subtitle(tmp_path / "Serie.S01E02.mkv")


def test_exact_basename_preferred_over_episode_fallback(tmp_path):
    make_files(tmp_path, "Serie.S01E02.1080p.de.srt", "Serie.S01E02.de.srt")
    assert find_injection_subtitle(tmp_path / "Serie.S01E02.1080p.mkv").name == "Serie.S01E02.1080p.de.srt"


def test_no_match_and_language_substrings(tmp_path):
    make_files(tmp_path, "Film.demo.srt", "Film.deutsch.srt", "Serie.S01E03.de.srt")
    with pytest.raises(ValueError, match="Keine passenden"):
        find_injection_subtitle(tmp_path / "Film.mkv")


@pytest.mark.parametrize("backend", ["mkvmerge", "ffmpeg"])
def test_metadata_applied_to_new_track(tmp_path, backend):
    from dragontools.subtitle import injector
    output = tmp_path / "output.mkv"
    commands = []

    def run(cmd, **kwargs):
        commands.append(cmd)
        output.write_bytes(b"muxed")
        return SimpleNamespace(ok=True)

    with patch.object(injector, "run_tool", side_effect=run):
        if backend == "mkvmerge":
            assert injector.inject_with_mkvmerge("video.mkv", "sub.srt", str(output), language="deu", title="Deutsch GPT")
            assert commands[0][commands[0].index("--track-name") + 1] == "0:Deutsch GPT"
        else:
            assert injector.inject_with_ffmpeg("video.mkv", "sub.srt", str(output), language="eng", title="Custom", existing_subtitle_count=2)
            cmd = commands[0]
            assert "-metadata:s:s:2" in cmd
            assert "language=eng" in cmd and "title=Custom" in cmd
            assert "-metadata:s:s:0" not in cmd


def test_worker_automatic_lookup_skips_missing_episode(tmp_path):
    pytest.importorskip("PyQt6")
    from dragontools.gui import subtitle_widget_workers as workers
    make_files(tmp_path, "Serie.S01E02.de.srt")
    tools = SimpleNamespace(mkvmerge="mkvmerge", ffmpeg="ffmpeg", ffprobe="ffprobe")
    worker = workers._InjectWorker([str(tmp_path / "Serie.S01E02.mkv"), str(tmp_path / "Serie.S01E03.mkv")], "", "deu", False, tools, title="Custom")
    logs, progress = [], []
    worker.log.connect(logs.append)
    worker.progress.connect(lambda done, total: progress.append((done, total)))
    with patch.object(workers, "inject_with_mkvmerge", return_value=True) as mux:
        worker.run()
    assert mux.call_count == 1
    assert Path(mux.call_args.args[1]).name == "Serie.S01E02.de.srt"
    assert mux.call_args.kwargs["title"] == "Custom"
    assert any("Übersprungen" in text for text in logs)
    assert progress == [(1, 2), (2, 2)]


def test_language_default_and_custom_title_preservation(qtbot, monkeypatch):
    from dragontools.gui import subtitle_widget
    monkeypatch.setattr(subtitle_widget, "get_tool_paths", lambda: SimpleNamespace())
    widget = subtitle_widget.SubtitleWidget()
    qtbot.addWidget(widget)
    assert widget.inj_lang.currentData() == "deu"
    assert widget.inj_title.currentText() == "Deutsch"
    widget.inj_lang.setCurrentIndex(1)
    assert widget.inj_title.currentText() == "Englisch"
    widget.inj_title.setEditText("Custom")
    widget.inj_lang.setCurrentIndex(0)
    assert widget.inj_title.currentText() == "Custom"
