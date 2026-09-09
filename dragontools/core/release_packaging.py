# -*- coding: utf-8 -*-
"""Sichere Erstellung von DragonTools-Quellrelease-ZIPs.

Release-Archive duerfen keine Python-Bytecode-/Cache-Artefakte enthalten.
Die Erstellung erfolgt ueber eine temporaere ZIP-Datei und atomaren Replace,
damit ein fehlgeschlagener Packvorgang kein vorhandenes Release ueberschreibt.
"""
from __future__ import annotations

import os
import shutil
import uuid
import zipfile
from pathlib import Path, PurePosixPath


FORBIDDEN_RELEASE_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
FORBIDDEN_RELEASE_SUFFIXES = frozenset({".pyc", ".pyo"})
ROOT_LOCAL_CACHE_DIRS = frozenset({".pytest_cache", ".mypy_cache", ".ruff_cache"})
IGNORED_RELEASE_DIRS = frozenset({
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".git",
    ".venv",
    "venv",
    "build",
    "dist",
    "git release",
    "projekt",
    "third_party",
})
EXCLUDED_LOCAL_TREES = IGNORED_RELEASE_DIRS - FORBIDDEN_RELEASE_DIRS


def _is_ignored_release_dir(name: str) -> bool:
    """True fuer lokale, generierte oder bewusst externe Release-Verzeichnisse."""
    normalized = name.casefold()
    return normalized in IGNORED_RELEASE_DIRS or normalized.startswith(".pytest_tmp")


def _is_excluded_local_tree(name: str) -> bool:
    """True fuer lokale Baeume, die niemals zum Quellrelease gehoeren."""
    normalized = name.casefold()
    return normalized in EXCLUDED_LOCAL_TREES or normalized.startswith(".pytest_tmp")


def is_forbidden_release_path(path: str | Path) -> bool:
    """True fuer Bytecode-/Cachepfade, die niemals ins Release duerfen."""
    normalized = str(path).replace("\\", "/")
    pure = PurePosixPath(normalized)
    parts = {part.casefold() for part in pure.parts}
    if parts & FORBIDDEN_RELEASE_DIRS:
        return True
    return pure.suffix.casefold() in FORBIDDEN_RELEASE_SUFFIXES


def find_forbidden_release_artifacts(root: str | Path) -> list[Path]:
    """Findet verbotene Artefakte in den tatsaechlichen Quellrelease-Pfaden."""
    base = Path(root)
    if not base.exists():
        return []

    findings: list[Path] = []
    base = base.resolve()
    
    for directory, dirnames, filenames in os.walk(base):
        current = Path(directory)
    
        dirnames[:] = [
            name
            for name in dirnames
            if not _is_excluded_local_tree(name)
        ]
        for name in [*dirnames, *filenames]:
            relative = (current / name).relative_to(base)
            if is_forbidden_release_path(relative):
                findings.append(relative)
    return sorted(findings, key=lambda item: item.as_posix().casefold())


def clean_forbidden_release_artifacts(root: str | Path) -> list[Path]:
    """Entfernt Bytecode-/Cache-Artefakte aus einem Projektbaum.

    Die Rueckgabe enthaelt die relativ zum Projektroot entfernten Pfade.
    Fehlende Dateien sind unkritisch; echte Loeschfehler werden bewusst nicht
    verschluckt, damit ein Release nicht faelschlich als sauber gilt.
    """
    base = Path(root).resolve()
    if not base.exists():
        return []

    removed: list[Path] = []
    cache_dirs: list[Path] = []
    bytecode_files: list[Path] = []
    for directory, dirnames, filenames in os.walk(base):
        current = Path(directory)
        kept_dirs: list[str] = []
        for name in dirnames:
            if _is_excluded_local_tree(name):
                continue
            path = current / name
            if name.casefold() in FORBIDDEN_RELEASE_DIRS:
                cache_dirs.append(path)
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs
        bytecode_files.extend(
            current / name
            for name in filenames
            if Path(name).suffix.casefold() in FORBIDDEN_RELEASE_SUFFIXES
        )

    cache_dirs.sort(key=lambda path: len(path.parts), reverse=True)
    for path in cache_dirs:
        try:
            relative = path.relative_to(base)
        except ValueError:
            continue
        try:
            shutil.rmtree(path)
        except PermissionError:
            # Root-Level pytest/mypy/ruff-Caches sind nur lokaler
            # Entwicklungszustand und werden grundsätzlich nicht ins
            # Release übernommen.
            #
            # Unter Windows kann z. B. PyCharm, Spyder, VS Code oder
            # ein laufender pytest-Prozess den Cache kurzfristig sperren.
            # Das darf den Release-Build nicht abbrechen.
            #
            # Caches innerhalb des eigentlichen Quellpakets bleiben
            # dagegen weiterhin strikt.
            if (
                len(relative.parts) == 1
                and relative.name.casefold() in ROOT_LOCAL_CACHE_DIRS
            ):
                continue
        
            raise
        
        removed.append(relative)

    for path in sorted(bytecode_files):
        if not path.is_file():
            continue
        try:
            relative = path.relative_to(base)
        except ValueError:
            continue
        path.unlink()
        removed.append(relative)

    return sorted(set(removed), key=lambda item: item.as_posix().casefold())


def _iter_release_files(root: Path, *, excluded_paths: set[Path]) -> list[Path]:
    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            name for name in dirnames
            if not _is_ignored_release_dir(name)
        ]
        base = Path(directory)
        for filename in filenames:
            path = base / filename
            try:
                resolved = path.resolve()
            except OSError:
                resolved = path.absolute()
            if resolved in excluded_paths:
                continue
            relative = path.relative_to(root)
            if is_forbidden_release_path(relative):
                continue
            files.append(path)
    return sorted(files, key=lambda item: item.relative_to(root).as_posix().casefold())


def create_source_release_zip(project_root: str | Path, target_zip: str | Path) -> Path:
    """Erstellt ein gefiltertes Source-ZIP ohne ``__pycache__``/``*.pyc``/``*.pyo``.

    Das bestehende Ziel wird erst ersetzt, wenn das temporaere Archiv erfolgreich
    geschrieben und anschliessend nochmals auf verbotene ZIP-Eintraege geprueft
    wurde.
    """
    root = Path(project_root).resolve()
    target = Path(target_zip).resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)

    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_name(f".{target.name}.partial.{uuid.uuid4().hex}")
    excluded = {target, temp}

    try:
        with zipfile.ZipFile(temp, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in _iter_release_files(root, excluded_paths=excluded):
                archive.write(path, arcname=path.relative_to(root).as_posix())

        with zipfile.ZipFile(temp, "r") as archive:
            forbidden = [name for name in archive.namelist() if is_forbidden_release_path(name)]
            if forbidden:
                raise RuntimeError(
                    "Release-ZIP enthaelt verbotene Bytecode-Artefakte: "
                    + ", ".join(forbidden[:10])
                )
            bad_member = archive.testzip()
            if bad_member is not None:
                raise RuntimeError(f"CRC-Fehler im Release-ZIP: {bad_member}")

        os.replace(temp, target)
        return target
    except Exception:
        try:
            temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
