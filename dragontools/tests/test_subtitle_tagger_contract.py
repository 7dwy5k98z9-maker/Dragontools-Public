from __future__ import annotations

from types import SimpleNamespace


def test_mkvpropedit_uses_configured_path_ordinal_track_and_accepts_warning(monkeypatch):
    from dragontools.subtitle import tagger

    captured = {}
    monkeypatch.setattr(tagger, "get_tool_paths", lambda: SimpleNamespace(mkvpropedit="/tools/mkvpropedit"))

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return SimpleNamespace(returncode=1, stdout="warning", stderr="")

    monkeypatch.setattr(tagger, "run_analysis_tool", fake_run)
    logs = []

    assert tagger.set_track_language("film.mkv", 2, "de", logger=logs.append) is True
    assert captured["cmd"][0] == "/tools/mkvpropedit"
    assert "track:3" in captured["cmd"]
    assert all("track:@" not in part for part in captured["cmd"])
    assert captured["kwargs"]["allow_error"] is True
    assert logs and "Returncode 1" in logs[0]


def test_mkvpropedit_rc2_is_failure(monkeypatch):
    from dragontools.subtitle import tagger

    monkeypatch.setattr(tagger, "get_tool_paths", lambda: SimpleNamespace(mkvpropedit="mkvpropedit"))
    monkeypatch.setattr(
        tagger,
        "run_analysis_tool",
        lambda *_args, **_kwargs: SimpleNamespace(returncode=2, stdout="", stderr="boom"),
    )
    assert tagger.set_forced_flag("film.mkv", 0, True) is False
