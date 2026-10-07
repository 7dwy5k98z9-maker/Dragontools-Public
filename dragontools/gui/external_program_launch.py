"""One executable-selection policy for the main menu and tab manager."""
from pathlib import Path


_TOOL_MAP = {
    "HandBrake.exe": ("handbrake", ("HandBrake.exe",)),
    "Resolve.exe": ("davinci_resolve", ("Resolve.exe", "resolve")),
    "RenameMyTVSeries.exe": ("rmts", ("RenameMyTVSeries.exe", "rmts.exe")),
    "mkvtoolnix-gui.exe": ("mkv", ("mkvtoolnix-gui.exe",)),
}


def launch_external_program(owner, exe_name, *, tools, find_bundled, open_external, choose):
    """Prefer configured executable, Resolve fallback, legacy path, then bundle."""
    candidates = []
    if exe_name in _TOOL_MAP:
        key, names = _TOOL_MAP[exe_name]
        candidates.append(tools.find_in_settings(key, *names))
    if exe_name == "Resolve.exe":
        candidates.append(tools.davinci_resolve)
    candidates.append(owner._settings.value(f"tools/external/{exe_name}", "", type=str))
    for path in candidates:
        if path and Path(path).is_file():
            open_external(path)
            return
    found = find_bundled(exe_name)
    if found and Path(found).is_file():
        open_external(found)
        return
    path, _ = choose(owner, f"{exe_name} wählen", "", f"Programm ({exe_name});;Alle Dateien (*)")
    if path and Path(path).is_file():
        owner._settings.setValue(f"tools/external/{exe_name}", path)
        open_external(path)
