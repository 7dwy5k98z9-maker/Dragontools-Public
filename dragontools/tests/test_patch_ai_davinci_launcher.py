from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
GUI = ROOT / "dragontools" / "gui"


def _source(name: str) -> str:
    return (GUI / name).read_text(encoding="utf-8")


def test_davinci_resolve_is_exposed_as_external_program_in_menus() -> None:
    source = _source("main_window_menus.py")
    assert source.count('"🎨 DaVinci Resolve öffnen"') == 2
    assert source.count('self._launch_external("Resolve.exe")') == 2


def test_main_window_launcher_maps_resolve_to_central_tool_key() -> None:
    source = _source("main_window_system_actions.py")
    assert 'launch_external_program(' in source
    shared = _source("external_program_launch.py")
    assert '"Resolve.exe": ("davinci_resolve", ("Resolve.exe", "resolve"))' in shared
    assert 'candidates.append(tools.davinci_resolve)' in shared
    assert 'if path and Path(path).is_file()' in shared


def test_tab_manager_exposes_and_resolves_davinci() -> None:
    source = _source("tab_manager.py")
    assert '("DaVinci Resolve", "Resolve.exe")' in source
    assert 'launch_external_program(' in source
    shared = _source("external_program_launch.py")
    assert '"Resolve.exe": ("davinci_resolve", ("Resolve.exe", "resolve"))' in shared
    assert 'candidates.append(tools.davinci_resolve)' in shared
    assert 'EXE_DIR / "Daten" / "Programme" / "davinci_resolve" / name' in source
