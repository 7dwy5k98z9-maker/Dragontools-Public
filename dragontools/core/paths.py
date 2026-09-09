# -*- coding: utf-8 -*-
"""
Zentrale Pfad- und Tool-Verwaltung für DragonTools V9.
Einmalig instantiiert, von allen Modulen genutzt.
Ersetzt die verstreuten ffmpeg_path(), find_tool(), resource_path() aus dem Altcode.
"""
from __future__ import annotations

import os
import shutil
import sys
from abc import ABC, abstractmethod
from pathlib import Path

# ---------------------------------------------------------------------------
# Settings-Provider-Interface (Qt-freie Abstraktion für core-Schicht)
# ---------------------------------------------------------------------------

class ToolPathSettingsProvider(ABC):
    """Interface für den Zugriff auf benutzerdefinierte Tool-Einstellungen.

    Entkoppelt core.paths von Qt: Die Implementierung (QtToolPathSettingsProvider
    in gui/tool_path_settings.py) liest QSettings; Tests oder CLI-Nutzung können
    eine eigene Implementierung ohne Qt einsetzen.
    """

    @abstractmethod
    def get_custom_dirs(self) -> list[Path]:
        """Gibt alle konfigurierten Tool-Verzeichnisse zurück (nur existierende)."""

    @abstractmethod
    def find_in_settings(self, tool_key: str, *exe_names: str) -> str | None:
        """Sucht ein Executable im für tool_key konfigurierten Verzeichnis.

        Gibt den vollständigen Pfad zurück oder None wenn nicht gefunden.
        """

# ---------------------------------------------------------------------------
# Basis-Pfade (frozen = PyInstaller-Bundle, sonst Entwicklungsverzeichnis)
# ---------------------------------------------------------------------------
FROZEN   = bool(getattr(sys, "frozen", False))
BASE     = (Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2])).resolve()
            if FROZEN else Path(__file__).resolve().parents[2])
EXE_DIR  = Path(sys.executable).parent.resolve() if FROZEN else BASE

PROGRAMME_DIR  = "Programme"
THIRD_PARTY_DIR = "third_party"          # Dev-Modus: Tools liegen hier statt in Programme/
THIRD_PARTY_TOOL_DIRS = (
    Path(THIRD_PARTY_DIR) / "FFmpeg",
    Path(THIRD_PARTY_DIR) / "MKVToolNix",
    Path(THIRD_PARTY_DIR) / "MakeMKV",
    Path(THIRD_PARTY_DIR) / "GPAC",
    Path(THIRD_PARTY_DIR) / "HandBrake",
    Path(THIRD_PARTY_DIR) / "Mediainfo",
    Path(THIRD_PARTY_DIR) / "dovi_tool",
    Path(THIRD_PARTY_DIR) / "hdr10plus_tool",
    Path(THIRD_PARTY_DIR) / "rmts",
)
PROGRAMME_TOOL_DIRS = (
    Path(PROGRAMME_DIR) / "FFmpeg",
    Path(PROGRAMME_DIR) / "mkvtoolnix",
    Path(PROGRAMME_DIR) / "MakeMKV",
    Path(PROGRAMME_DIR) / "GPAC",
    Path(PROGRAMME_DIR) / "handbrake",
    Path(PROGRAMME_DIR) / "mediainfo",
    Path(PROGRAMME_DIR) / "dovi_tool",
    Path(PROGRAMME_DIR) / "hdr10plus_tool",
    Path(PROGRAMME_DIR) / "rmts",
)
MKV_DIR       = f"{PROGRAMME_DIR}/mkvtoolnix"
RMTS_DIR      = f"{PROGRAMME_DIR}/rmts"
HB_DIR        = f"{PROGRAMME_DIR}/handbrake"
MEDIAINFO_DIR = f"{PROGRAMME_DIR}/mediainfo"
ICON_DIR      = "icon"
IMAGES_DIR    = "Bilder"

from .path_syntax import (
    VIDEO_EXTENSIONS,
    strip_long_path_prefix,
    is_windows_style_path,
    normalize_user_path,
    to_long_path,
    path_compare_key,
    user_path_name,
    user_path_stem,
    user_path_parent,
    join_user_path,
    path_is_same_or_child,
    display_path,
    display_name,
    is_video_file,
)
from .path_defaults import (
    DEFAULT_DOCUMENTS_DIRNAME,
    DEFAULT_OUTPUT_DIRNAME,
    DEFAULT_CODEC_DIRS,
    DEFAULT_MEDIA_TYPE_DIRS,
    app_documents_dir,
    default_output_base,
    default_target_path,
    default_target_paths,
    default_target_path_for_settings_key,
    ensure_default_storage_dirs,
)

def resource_path(rel: str) -> str:
    """Absoluter Pfad zu einer Ressource im Bundle oder Projektverzeichnis."""
    return str((BASE / rel).resolve())


def _known_tool_dirs() -> list[Path]:
    candidates: list[Path] = [BASE, EXE_DIR]
    relative_dirs = (
        Path(PROGRAMME_DIR),
        Path(THIRD_PARTY_DIR),
        *PROGRAMME_TOOL_DIRS,
        *THIRD_PARTY_TOOL_DIRS,
    )
    for rel in relative_dirs:
        candidates.extend((BASE / rel, EXE_DIR / rel, EXE_DIR / "Daten" / rel))
    return candidates


def extend_path(extra: list[Path] | None = None) -> None:
    """Bekannte Tool-Verzeichnisse einmalig und dedupliziert zum PATH hinzufügen."""
    candidates = _known_tool_dirs()
    if extra:
        candidates.extend(extra)

    # Nur existierende, normalisierte Pfade
    new_dirs: list[str] = []
    for p in candidates:
        try:
            if p.exists():
                new_dirs.append(str(p.resolve()))
        except Exception:
            pass

    current_raw = os.environ.get("PATH", "")
    current_parts = [p for p in current_raw.split(os.pathsep) if p]

    normalized_existing = set()
    cleaned_current: list[str] = []

    for p in current_parts:
        try:
            norm = str(Path(p).resolve())
        except Exception:
            norm = p
        if norm not in normalized_existing:
            normalized_existing.add(norm)
            cleaned_current.append(p)

    to_add: list[str] = []
    for p in new_dirs:
        if p not in normalized_existing:
            normalized_existing.add(p)
            to_add.append(p)

    os.environ["PATH"] = os.pathsep.join(to_add + cleaned_current)


def _resolve_tool_candidate(path: Path, executable_names: tuple[str, ...]) -> str | None:
    """Gibt nur echte Dateien zurück; Ordner werden nach passenden EXEs durchsucht."""
    try:
        if path.is_file():
            return str(path)
        if path.is_dir():
            for name in executable_names:
                nested = path / name
                if nested.is_file():
                    return str(nested)
    except Exception:
        return None
    return None


def find_tool(name: str, *alt_names: str) -> str:
    """
    Tool im PATH oder in bekannten Bundle-Verzeichnissen suchen.
    Gibt den gefundenen Pfad zurück, oder `name` als Fallback
    (damit Fehlermeldungen sinnvoll sind).
    """
    p = shutil.which(name)
    if not p:
        for a in alt_names:
            p = shutil.which(a)
            if p:
                break
    if p:
        return p
    search_roots = _known_tool_dirs()
    executable_names = (name, *alt_names)
    for root in search_roots:
        for cand in executable_names:
            path = root / cand
            resolved = _resolve_tool_candidate(path, executable_names)
            if resolved:
                return resolved
    return name


# ---------------------------------------------------------------------------
# ToolPaths: alle externen Tools zentral
# ---------------------------------------------------------------------------

class ToolPaths:
    """Zugriff auf alle externen Tool-Pfade.

    Nimmt beim Init einen optionalen ToolPathSettingsProvider entgegen.
    Ohne Provider (z.B. in Tests oder CLI) werden nur PATH und Bundle-
    Verzeichnisse durchsucht – kein Qt-Import nötig.

    In der GUI-Anwendung wird einmalig beim App-Start ein Provider
    übergeben (siehe gui/tool_path_settings.py, main_window.py):

        get_tool_paths(provider=QtToolPathSettingsProvider())
    """

    def __init__(self, provider: ToolPathSettingsProvider | None = None) -> None:
        self._provider = provider
        extend_path(extra=provider.get_custom_dirs() if provider is not None else None)
        self._cache: dict[str, str] = {}

    def _find(self, tool_key: str, *names: str) -> str:
        """Sucht ein Tool in dieser Reihenfolge:

        1. Konfigurierter Ordner aus dem Settings-Provider (wenn vorhanden)
        2. Windows PATH (inkl. custom dirs die wir hinzugefügt haben)
        3. Bundle-Verzeichnisse
        """
        cache_key = f"{tool_key}:{'|'.join(names)}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        result: str | None = None
        if self._provider is not None:
            result = self._provider.find_in_settings(tool_key, *names)
            if result:
                result = _resolve_tool_candidate(Path(result), names)
        if not result:
            result = find_tool(*names)

        self._cache[cache_key] = result
        return result

    def find_in_settings(self, tool_key: str, *exe_names: str) -> str | None:
        """Delegiert an den konfigurierten Provider.

        Ersetzt den früheren Modulaufruf find_tool_in_settings() für
        Code, der bereits eine ToolPaths-Instanz haelt (z.B. main_window).
        """
        if self._provider is None:
            return None
        return self._provider.find_in_settings(tool_key, *exe_names)

    @property
    def ffmpeg(self) -> str:
        return self._find("ffmpeg", "ffmpeg.exe", "ffmpeg")

    @property
    def ffprobe(self) -> str:
        # ffprobe liegt immer im gleichen Ordner wie ffmpeg
        # → nutzt den ffmpeg-Einstellungs-Key (kein eigener Key mehr)
        return self._find("ffmpeg", "ffprobe.exe", "ffprobe")

    @property
    def mkvmerge(self) -> str:
        return self._find("mkv", "mkvmerge.exe", "mkvmerge")

    @property
    def makemkvcon(self) -> str:
        return self._find("makemkvcon", "makemkvcon64.exe", "makemkvcon.exe", "makemkvcon")

    @property
    def mkvextract(self) -> str:
        return self._find("mkv", "mkvextract.exe", "mkvextract")

    @property
    def mkvinfo(self) -> str:
        return self._find("mkv", "mkvinfo.exe", "mkvinfo")

    @property
    def mkvpropedit(self) -> str:
        return self._find("mkv", "mkvpropedit.exe", "mkvpropedit")

    @property
    def mediainfo(self) -> str:
        return self._find("mediainfo", "MediaInfo.exe", "mediainfo.exe", "mediainfo", "MediaInfo")

    @property
    def dovi_tool(self) -> str:
        return self._find("dovi_tool", "dovi_tool.exe", "dovi_tool")

    @property
    def hdr10plus_tool(self) -> str:
        return self._find("hdr10plus_tool", "hdr10plus_tool.exe", "hdr10plus_tool")

    @property
    def mp4box(self) -> str:
        return self._find("mp4box", "MP4Box.exe", "mp4box.exe", "MP4Box", "mp4box")

    @property
    def handbrake_cli(self) -> str:
        # Suche HandBrake.exe (GUI-Version) UND HandBrakeCLI.exe
        # Im Bundle: Daten/Programme/handbrake/HandBrake.exe
        return self._find("handbrake",
                          "HandBrake.exe", "HandBrakeCLI.exe",
                          "HandBrake", "HandBrakeCLI", "handbrake_cli")
    
    @property
    def rmts(self) -> str:
        return self._find(
                          "rmts", "RenameMyTVSeries.exe",
                          "rmts.exe", "RenameMyTVSeries")

    def verify_all(self) -> dict[str, bool]:
        """Gibt zurück welche Tools tatsächlich gefunden wurden."""
        tools = {
                "ffmpeg":         self.ffmpeg,
                "ffprobe":        self.ffprobe,
                "mkvmerge":       self.mkvmerge,
                "makemkvcon":     self.makemkvcon,
                "mkvextract":     self.mkvextract,
                "rmts":           self.rmts,
                "handbrake":      self.handbrake_cli,
                "mediainfo":      self.mediainfo,
                "dovi_tool":      self.dovi_tool,
                "hdr10plus_tool": self.hdr10plus_tool,
                "mp4box":         self.mp4box,
                }
        return {
            name: (Path(path).exists() or bool(shutil.which(path)))
            for name, path in tools.items()
        }


# ---------------------------------------------------------------------------
# ToolPaths Singleton
# ---------------------------------------------------------------------------
_tool_paths_instance: ToolPaths | None = None
_tool_paths_provider: ToolPathSettingsProvider | None = None   # überlebt invalidate()
_tool_paths_lock = __import__("threading").Lock()


def get_tool_paths(provider: ToolPathSettingsProvider | None = None) -> ToolPaths:
    """Gibt die geteilte ToolPaths-Instanz zurück.

    Beim ersten Aufruf (typischerweise beim App-Start in main_window.py) sollte
    ein ``ToolPathSettingsProvider`` übergeben werden, damit benutzerdefinierte
    Tool-Verzeichnisse aus den Einstellungen geladen werden:

        from dragontools.gui.tool_path_settings import QtToolPathSettingsProvider
        get_tool_paths(provider=QtToolPathSettingsProvider())

    Alle weiteren Aufrufe geben die gecachte Instanz zurück; der ``provider``-
    Parameter wird nach dem ersten Aufruf ignoriert.

    Nach ``invalidate_tool_paths()`` (z.B. nach dem Speichern der Einstellungen)
    wird der Singleton neu erzeugt – dabei wird der zuletzt registrierte Provider
    automatisch wiederverwendet. Worker-Threads, die ``get_tool_paths()`` ohne
    Provider aufrufen, erhalten so stets eine vollständig initialisierte Instanz.

    Thread-sicher: mehrere Worker-Threads können gleichzeitig aufrufen,
    ohne dass mehrere Instanzen erzeugt werden.
    """
    global _tool_paths_instance, _tool_paths_provider
    if _tool_paths_instance is not None:
        return _tool_paths_instance
    with _tool_paths_lock:
        # Double-Checked Locking
        if _tool_paths_instance is None:
            # Provider merken, damit er nach invalidate() weiter genutzt wird.
            # Einmal registriert, bleibt er für die gesamte App-Laufzeit erhalten.
            if provider is not None:
                _tool_paths_provider = provider
            _tool_paths_instance = ToolPaths(provider=_tool_paths_provider)
        return _tool_paths_instance


def invalidate_tool_paths() -> None:
    """Verwirft die gecachte Instanz – z.B. nach Aenderungen in den Einstellungen.

    Der registrierte Provider bleibt erhalten: der naechste ``get_tool_paths()``-
    Aufruf erzeugt eine neue Instanz mit demselben Provider und liest dabei
    die aktuellen Einstellungen (extend_path, find_in_settings) neu ein.
    """
    global _tool_paths_instance
    with _tool_paths_lock:
        _tool_paths_instance = None
        # _tool_paths_provider bleibt absichtlich erhalten!
