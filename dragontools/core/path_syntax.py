# -*- coding: utf-8 -*-
"""Hostunabhängige Pfadsyntax-Helfer für Windows/UNC/POSIX/Jellyfin-Pfade."""
from __future__ import annotations

import ntpath
import os
import posixpath
import re
from pathlib import Path, PurePosixPath, PureWindowsPath

VIDEO_EXTENSIONS = {
    ".mkv",
    ".mp4",
    ".avi",
    ".mov",
    ".m4v",
    ".ts",
    ".m2ts",
    ".mts",
    ".webm",
    ".wmv",
    ".flv",
    ".mpg",
    ".mpeg",
    ".xvid",
    ".divx",
}


def strip_long_path_prefix(path: str | os.PathLike[str]) -> str:
    """Entfernt den Windows-Long-Path-Praefix rein textuell.

    Das muss auch auf Nicht-Windows-Hosts funktionieren, weil DragonTools
    Windows-/UNC-Pfade aus Datenbanken, Jellyfin und Reports verarbeiten kann,
    ohne dass diese Pfade auf dem aktuellen Host existieren muessen.
    """
    value = os.fspath(path)
    if value.startswith("\\\\?\\UNC\\"):
        return "\\\\" + value[8:]
    if value.startswith("\\\\?\\"):
        return value[4:]
    return value


def is_windows_style_path(path: str | os.PathLike[str]) -> bool:
    """Erkennt Windows-/UNC-Pfade unabhaengig vom Host-Betriebssystem."""
    raw = os.fspath(path).strip()
    if not raw:
        return False
    if raw.startswith(("\\\\", "//", "\\\\?\\")):
        return True
    if re.match(r"^[A-Za-z]:", raw):
        return True
    return "\\" in raw


def _normalize_windows_path_text(raw: str) -> str:
    had_prefix = raw.startswith("\\\\?\\")
    plain = strip_long_path_prefix(raw).replace("/", "\\")
    plain = ntpath.expanduser(plain)
    normalized = ntpath.normpath(plain)
    if had_prefix:
        if normalized.startswith("\\\\"):
            return "\\\\?\\UNC\\" + normalized.lstrip("\\")
        return "\\\\?\\" + normalized
    return normalized


def normalize_user_path(path: str | os.PathLike[str]) -> str:
    """Normalisiert Benutzerpfade ohne fremde Pfadsyntax zu zerstoeren.

    Windows-/UNC-Pfade werden auch auf POSIX-Hosts mit ``ntpath`` behandelt.
    Dadurch wird z. B. ``C:\\TV`` nicht mehr zu ``<cwd>/C:\\TV`` und
    ``//server/share`` konsistent als UNC-Pfad interpretiert.
    """
    raw = os.fspath(path).strip()
    if not raw:
        return ""

    if is_windows_style_path(raw):
        normalized = _normalize_windows_path_text(raw)
        if os.name == "nt" and not ntpath.isabs(strip_long_path_prefix(normalized)):
            normalized = ntpath.abspath(normalized)
        return normalized

    # Jellyfin-/Unix-Pfade wie /Anime/... sind Datenpfade und duerfen auf
    # Windows nicht gegen das aktuelle Laufwerk aufgeloest werden.
    if os.name == "nt" and raw.startswith("/"):
        return posixpath.normpath(raw)

    if os.name != "nt":
        return str(Path(raw).expanduser().resolve(strict=False))

    plain = os.path.expanduser(raw)
    return os.path.abspath(os.path.normpath(plain))


def to_long_path(path: str | os.PathLike[str]) -> str:
    raw = os.fspath(path).strip()
    if not raw:
        return ""
    if os.name != "nt":
        return normalize_user_path(raw)
    if raw.startswith("\\\\?\\"):
        return raw
    plain = strip_long_path_prefix(normalize_user_path(raw))
    if plain.startswith("\\\\"):
        return "\\\\?\\UNC\\" + plain.lstrip("\\")
    return "\\\\?\\" + plain


def path_compare_key(path: str | os.PathLike[str]) -> str:
    """Vergleichsschluessel fuer lokale und gespeicherte Pfade.

    Windows-Pfade sind wie unter Windows case-insensitive und verwenden immer
    Backslashes; POSIX-Pfade behalten ihre normale Case-Semantik.
    """
    raw = os.fspath(path).strip()
    value = normalize_user_path(raw)
    if is_windows_style_path(raw) or is_windows_style_path(value):
        return ntpath.normcase(ntpath.normpath(strip_long_path_prefix(value)))
    return value


def _pure_user_path(path: str | os.PathLike[str]) -> PureWindowsPath | PurePosixPath:
    """Liefert eine rein syntaktische Pfadklasse ohne Dateisystemzugriff."""
    raw = os.fspath(path).strip()
    if is_windows_style_path(raw):
        return PureWindowsPath(strip_long_path_prefix(_normalize_windows_path_text(raw)))
    return PurePosixPath(posixpath.normpath(raw))


def user_path_name(path: str | os.PathLike[str]) -> str:
    """Basename fuer Windows-/UNC-/Jellyfin-/POSIX-Pfade, hostunabhaengig."""
    raw = os.fspath(path).strip()
    if not raw:
        return ""
    return _pure_user_path(raw).name


def user_path_stem(path: str | os.PathLike[str]) -> str:
    """Dateistamm fuer gemischte Pfadsyntax, hostunabhaengig."""
    raw = os.fspath(path).strip()
    if not raw:
        return ""
    return _pure_user_path(raw).stem


def user_path_parent(path: str | os.PathLike[str]) -> str:
    """Parent-Pfad rein syntaktisch und ohne Host-Uminterpretation."""
    raw = os.fspath(path).strip()
    if not raw:
        return ""
    return str(_pure_user_path(raw).parent)


def join_user_path(base: str | os.PathLike[str], *parts: str | os.PathLike[str]) -> str:
    """Fuegt Segmente mit der Syntax des Basisordners zusammen.

    Windows-/UNC-Basen erhalten Backslashes. POSIX-/Jellyfin-Basen erhalten
    Forward-Slashes. Es findet kein Dateisystemzugriff statt.
    """
    raw_base = os.fspath(base).strip()
    if not raw_base:
        return ""
    if is_windows_style_path(raw_base):
        normalized_base = _normalize_windows_path_text(raw_base)
        clean_parts = [os.fspath(part).replace("/", "\\").strip("\\/") for part in parts]
        return ntpath.normpath(ntpath.join(normalized_base, *clean_parts))
    normalized_base = posixpath.normpath(raw_base)
    clean_parts = [os.fspath(part).replace("\\", "/").strip("/") for part in parts]
    return posixpath.normpath(posixpath.join(normalized_base, *clean_parts))


def path_is_same_or_child(path: str | os.PathLike[str], base: str | os.PathLike[str]) -> bool:
    """True, wenn ``path`` dem Basisordner entspricht oder darunter liegt."""
    candidate = path_compare_key(path)
    base_key = path_compare_key(base)
    if not candidate or not base_key:
        return False
    if candidate == base_key:
        return True
    windows = is_windows_style_path(path) or is_windows_style_path(base)
    sep = "\\" if windows else "/"
    return candidate.startswith(base_key.rstrip("\\/") + sep)


def display_path(path: str | os.PathLike[str], max_len: int = 96) -> str:
    value = strip_long_path_prefix(normalize_user_path(path))
    if len(value) <= max_len:
        return value
    head = max(20, max_len // 2 - 2)
    tail = max(15, max_len - head - 3)
    return f"{value[:head]}...{value[-tail:]}"


def display_name(path: str | os.PathLike[str]) -> str:
    value = strip_long_path_prefix(normalize_user_path(path))
    name = user_path_name(value)
    return name or value


def is_video_file(path: str | os.PathLike[str]) -> bool:
    value = os.fspath(path).strip()
    if not value:
        return False
    suffix = Path(strip_long_path_prefix(value)).suffix.lower()
    return suffix in VIDEO_EXTENSIONS
