from __future__ import annotations

from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


def test_handbrake_resolution_uses_desktop_exe_only(tmp_path: Path) -> None:
    from dragontools.core.tool_paths import ToolPaths

    root = tmp_path / "handbrake"
    root.mkdir()
    desktop = root / "HandBrake.exe"
    desktop.write_bytes(b"exe")

    class Provider:
        def find_in_settings(self, tool_key: str, *exe_names: str):
            assert tool_key == "handbrake"
            assert "HandBrake.exe" in exe_names
            assert "HandBrakeCLI.exe" not in exe_names
            for name in exe_names:
                candidate = root / name
                if candidate.exists():
                    return str(candidate)
            return None

        def get_custom_dirs(self):
            return []

    tools = ToolPaths(provider=Provider())
    assert Path(tools.handbrake) == desktop
    assert tools.handbrake_cli == tools.handbrake  # legacy compatibility alias


def test_live_tool_check_searches_handbrake_desktop_exe() -> None:
    source = (PACKAGE_ROOT / "gui" / "tool_path_live_check.py").read_text(encoding="utf-8")
    assert '"handbrake", "HandBrake.exe", "HandBrake"' in source
    assert '"handbrake", "HandBrakeCLI.exe"' not in source


def test_runtime_settings_auto_searches_handbrake_desktop_exe() -> None:
    source = (PACKAGE_ROOT / "gui" / "settings_sections" / "runtime.py").read_text(encoding="utf-8")
    assert '"handbrake": ("HandBrake.exe", "HandBrake")' in source
    assert '(tp.handbrake, "HandBrake.exe")' in source


def test_whisper_cache_is_reported_separately_from_runtime(monkeypatch, tmp_path: Path) -> None:
    import dragontools.core.whisper_runtime as runtime

    cache_root = tmp_path / "hub"
    snapshot = cache_root / "models--Systran--faster-whisper-small" / "snapshots" / "abc"
    snapshot.mkdir(parents=True)
    (snapshot / "model.bin").write_bytes(b"model")
    (snapshot / "config.json").write_text("{}", encoding="utf-8")

    monkeypatch.setattr(runtime, "_cache_roots", lambda: (cache_root,))
    monkeypatch.setattr(runtime, "_module_available", lambda _name: True)
    monkeypatch.setattr(runtime, "package_version", lambda name: "1.2.3")

    row = runtime.build_whisper_diagnostic(model_name="small", use_local_model=False)

    assert row["found"] is True
    assert str(snapshot) == row["path"]
    assert "Modellcache 'small' vorhanden" in row["features"]
    assert row["error"] == ""


def test_missing_whisper_runtime_explains_model_cache_does_not_replace_packages(monkeypatch) -> None:
    import dragontools.core.whisper_runtime as runtime

    monkeypatch.setattr(runtime, "_module_available", lambda _name: False)
    monkeypatch.setattr(runtime, "find_cached_whisper_model", lambda _name="small": None)

    row = runtime.build_whisper_diagnostic(model_name="small", use_local_model=False)

    assert row["found"] is False
    assert "Modellcache enthält nur Modelldaten" in row["error"]
    assert "Python/CTranslate2-Laufzeit" in row["error"]


def test_missing_model_cache_is_not_an_error_when_runtime_is_available(monkeypatch) -> None:
    import dragontools.core.whisper_runtime as runtime

    monkeypatch.setattr(runtime, "_module_available", lambda _name: True)
    monkeypatch.setattr(runtime, "find_cached_whisper_model", lambda _name="small": None)
    monkeypatch.setattr(runtime, "package_version", lambda _name: "")

    row = runtime.build_whisper_diagnostic(model_name="small", use_local_model=False)

    assert row["found"] is True
    assert "beim ersten tatsächlichen Einsatz automatisch geladen" in row["error"]
    assert any("Download bei erster Nutzung" in item for item in row["features"])
