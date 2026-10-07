# -*- coding: utf-8 -*-
"""Sichere Erstellung von DragonTools-Quellrelease-ZIPs.

Release-Archive duerfen keine Python-Bytecode-/Cache-Artefakte enthalten.
Die Erstellung erfolgt ueber eine temporaere ZIP-Datei und atomaren Replace,
damit ein fehlgeschlagener Packvorgang kein vorhandenes Release ueberschreibt.
"""
from __future__ import annotations

import os
import re
import shutil
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from .release_private_paths import LOCAL_CREDENTIAL_DIRS, is_private_source_path, sanitize_user_path
from .release_source_identity import capture_source_inventory, require_source_inventory
from .release_archive_commit import publish_release_archive
from .transaction_identity import path_receipt, object_identity, same_object


FORBIDDEN_RELEASE_DIRS = frozenset({"__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache"})
FORBIDDEN_RELEASE_SUFFIXES = frozenset({".pyc", ".pyo", ".spec"})
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
    "comfyui_windows_portable",
    "hdrtvdm",
})
EXCLUDED_LOCAL_TREES = IGNORED_RELEASE_DIRS - FORBIDDEN_RELEASE_DIRS



PUBLIC_TEXT_SUFFIXES = frozenset({
    ".bat", ".cfg", ".html", ".ini", ".json", ".md", ".py", ".toml",
    ".txt", ".xml", ".yaml", ".yml",
})

_PRIVATE_SERVER_BACKSLASH_PATTERN = r"\\\\medien" + "speicher"
_PRIVATE_SERVER_FORWARD_PATTERN = r"//medien" + "speicher"
_PRIVATE_WORKDIR_PATTERN = "Arbeitsordner " + "codex"
_PRIVATE_ORG_PATTERN = "Mark" + "usTools"
_PRIVATE_AUTHOR_PATTERN = "Mark" + "us Developer"
_PRIVATE_FIRST_NAME_PATTERN = r"\bMark" + r"us\b|\bMark" + r"u\b"

_PUBLIC_SANITIZERS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"C:\\Users\\<USER>\\\r\n]+", re.IGNORECASE), r"C:\\Users\\<USER>"),
    (re.compile(r"AppData\\Local\\Temp\\codex-[^\\\r\n]+", re.IGNORECASE), r"AppData\\Local\\Temp\\<TEMP>"),
    (re.compile(_PRIVATE_SERVER_BACKSLASH_PATTERN, re.IGNORECASE), r"\\\\<SERVER>"),
    (re.compile(_PRIVATE_SERVER_FORWARD_PATTERN, re.IGNORECASE), "//<SERVER>"),
    (re.compile(_PRIVATE_WORKDIR_PATTERN, re.IGNORECASE), "<PROJECT_ROOT>"),
    (re.compile(_PRIVATE_ORG_PATTERN, re.IGNORECASE), "DragonTools"),
    (re.compile(_PRIVATE_AUTHOR_PATTERN, re.IGNORECASE), "DragonTools Team"),
    (re.compile(_PRIVATE_FIRST_NAME_PATTERN, re.IGNORECASE), "DragonTools"),
)

def sanitize_public_text(text: str) -> str:
    result = sanitize_user_path(str(text))
    for pattern, replacement in _PUBLIC_SANITIZERS:
        result = pattern.sub(replacement, result)
    return result

def _write_public_member(archive: zipfile.ZipFile, root: Path, path: Path, *, sanitize: bool) -> None:
    arcname = path.relative_to(root).as_posix()
    if sanitize and path.suffix.casefold() in PUBLIC_TEXT_SUFFIXES:
        text = path.read_text(encoding="utf-8")
        archive.writestr(arcname, sanitize_public_text(text).encode("utf-8"))
        return
    archive.write(path, arcname=arcname)

# Kanonischer öffentlicher Source-Release-Vertrag. Private Snapshot-/Review-
# Artefakte bleiben im Arbeitsbaum, gehören aber nicht in das öffentliche
# Quellarchiv. DragonTools_Source_ZIP.bat delegiert an dieselbe Funktion, damit
# es nur noch genau eine Inventar-Policy gibt.
PUBLIC_SOURCE_REQUIRED_DIRS = frozenset({"dragontools", "dragon_hdr10plus_generator", ".github"})
PUBLIC_SOURCE_OPTIONAL_DIRS = frozenset({
    "tests", "config", "core", "gui", "rules", "subtitle", "worker",
    "handbuch", "aenderungshistorie", "icon", "bilder", "extras",
})
PUBLIC_SOURCE_REQUIRED_ROOT_FILES = frozenset({
    "build_v9.bat",
    "DragonTools_Source_ZIP.bat",
    "README.md",
    "PATCH.md",
    "help.html",
    "release_manifest.json",
    "pytest.ini",
    "INTEGRATION_TESTS.md",
    "COMFYUI_HDR_SETUP.md",
    "requirements-runtime.txt",
    "requirements-optional.txt",
    "requirements-test.txt",
    "requirements-build.txt",
    "requirements-whisper.txt",
})
PUBLIC_SOURCE_OPTIONAL_ROOT_FILES = frozenset({
    "build_v9_angepasst.bat",
    "DragonToolsV9_Dokumentation.docx",
    "Dokumentation.docx",
    "Info.txt",
    "pyproject.toml",
    "setup.cfg",
    "tox.ini",
    ".gitignore",
    "LICENSE",
    "LICENSE.txt",
    "CHANGELOGV8.txt",
    "CHANGELOGV7.txt",
})


def _is_dragontools_project(root: Path) -> bool:
    return (root / "dragontools").is_dir() and (root / "build_v9.bat").is_file()


def _public_source_path_allowed(relative: Path) -> bool:
    parts = relative.parts
    if not parts:
        return False
    if len(parts) > 1:
        first = parts[0].casefold()
        return first in PUBLIC_SOURCE_REQUIRED_DIRS or first in PUBLIC_SOURCE_OPTIONAL_DIRS

    name = relative.name
    if name in PUBLIC_SOURCE_REQUIRED_ROOT_FILES or name in PUBLIC_SOURCE_OPTIONAL_ROOT_FILES:
        return True
    if relative.suffix.casefold() == ".py":
        return True
    return name.casefold().startswith("requirements") and relative.suffix.casefold() == ".txt"


def _validate_public_source_contract(root: Path) -> None:
    missing_dirs = sorted(name for name in PUBLIC_SOURCE_REQUIRED_DIRS if not (root / name).is_dir())
    missing_files = sorted(name for name in PUBLIC_SOURCE_REQUIRED_ROOT_FILES if not (root / name).is_file())
    if missing_dirs or missing_files:
        detail = []
        if missing_dirs:
            detail.append("Ordner: " + ", ".join(missing_dirs))
        if missing_files:
            detail.append("Dateien: " + ", ".join(missing_files))
        raise FileNotFoundError("Öffentlicher Source-Release unvollständig: " + "; ".join(detail))
    build = (root / 'build_v9.bat').read_text(encoding='utf-8')
    if '-m extras.release_pyinstaller' in build and not (root / 'extras/release_pyinstaller.py').is_file():
        raise FileNotFoundError('Source-Release: extras/release_pyinstaller.py fehlt für den nativen Builder.')


def iter_public_source_files(root: str | Path) -> list[Path]:
    """Liefert exakt das kanonische Inventar des öffentlichen Source-Releases.

    Für kleine generische Testprojekte ohne DragonTools-Signatur bleibt die
    Funktion absichtlich generisch; im echten Projekt greift der explizite
    öffentliche Release-Vertrag.
    """
    base = Path(root).resolve()
    canonical = _is_dragontools_project(base)
    if canonical:
        _validate_public_source_contract(base)

    files: list[Path] = []
    for directory, dirnames, filenames in os.walk(base):
        current = Path(directory)
        try:
            current_rel = current.relative_to(base)
        except ValueError:
            continue

        kept_dirs: list[str] = []
        for name in dirnames:
            candidate_dir = current / name
            if candidate_dir.is_symlink() or candidate_dir.is_junction():
                raise RuntimeError(f"Verzeichnisverknüpfung im Source-Release nicht erlaubt: {candidate_dir}")
            if _is_ignored_release_dir(name):
                continue
            rel_dir = current_rel / name if current_rel.parts else Path(name)
            if canonical and not _public_source_path_allowed(rel_dir / "__placeholder__"):
                continue
            kept_dirs.append(name)
        dirnames[:] = kept_dirs

        for filename in filenames:
            path = current / filename
            if path.is_symlink():
                raise RuntimeError(f"Symlink im Source-Release nicht erlaubt: {path}")
            relative = path.relative_to(base)
            if canonical and not _public_source_path_allowed(relative):
                continue
            if is_forbidden_release_path(relative) or is_private_source_path(relative):
                continue
            files.append(path)

    return sorted(files, key=lambda item: item.relative_to(base).as_posix().casefold())


def _is_ignored_release_dir(name: str) -> bool:
    """True fuer lokale, generierte oder bewusst externe Release-Verzeichnisse."""
    normalized = name.casefold()
    return normalized in IGNORED_RELEASE_DIRS or normalized in LOCAL_CREDENTIAL_DIRS or normalized.startswith(".pytest_tmp")


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
    for path in iter_public_source_files(root):
        try:
            resolved = path.resolve()
        except OSError:
            resolved = path.absolute()
        if resolved in excluded_paths:
            continue
        files.append(path)
    return files


def create_source_release_zip(project_root: str | Path, target_zip: str | Path) -> Path:
    """Erstellt ein gefiltertes Source-ZIP ohne ``__pycache__``/``*.pyc``/``*.pyo``.

    Das bestehende Ziel wird erst ersetzt, wenn das temporaere Archiv erfolgreich
    geschrieben und anschliessend nochmals auf verbotene ZIP-Eintraege geprueft
    wurde.
    """
    root = Path(project_root).resolve()
    requested_target = Path(target_zip).absolute()
    if requested_target.suffix.casefold() != ".zip" or requested_target.is_symlink():
        raise ValueError("Source-Release-Ziel muss eine reguläre ZIP-Datei sein.")
    target = requested_target.resolve()
    if not root.is_dir():
        raise NotADirectoryError(root)

    target.parent.mkdir(parents=True, exist_ok=True)
    destination_receipt = path_receipt(target) if target.exists() else None
    files = _iter_release_files(root, excluded_paths={target})
    inventory = capture_source_inventory(files)

    # Credentials must never reach a public source archive. Private names/paths
    # may be sanitized below, but real secret findings are a hard release gate.
    from .release_validation_privacy import _scan_private_markers
    privacy_errors = [item for item in _scan_private_markers(root) if item.status == "error"]
    if privacy_errors:
        preview = "; ".join(item.detail for item in privacy_errors[:5])
        raise RuntimeError(f"Source-Release wegen möglicher Secrets abgebrochen: {preview}")

    require_source_inventory(inventory, _iter_release_files(root, excluded_paths={target}))
    temp = target.with_name(f".{target.name}.partial.{uuid.uuid4().hex}")
    excluded = {target, temp}

    temp_identity = None
    try:
        with zipfile.ZipFile(temp, "x", compression=zipfile.ZIP_DEFLATED) as archive:
            temp_identity = object_identity(temp)
            sanitize = _is_dragontools_project(root)
            for path in files:
                _write_public_member(archive, root, path, sanitize=sanitize)

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

        require_source_inventory(inventory, _iter_release_files(root, excluded_paths=excluded))
        publish_release_archive(temp, target, destination_receipt=destination_receipt)
        return target
    except Exception:
        try:
            if same_object(temp, temp_identity):
                temp.unlink(missing_ok=True)
        except OSError:
            pass
        raise
