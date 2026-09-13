from __future__ import annotations

from pathlib import Path

_DIRECTORY_ITEM_TYPES = {"series", "season"}


def _path_is_directory(item_type: str, path: Path) -> bool:
    """Classify a media path without treating dotted folder names as files."""
    try:
        if path.exists():
            return path.is_dir()
    except OSError:
        pass
    return str(item_type or "").casefold() in _DIRECTORY_ITEM_TYPES


def _media_directory(item_type: str, media_path: str) -> Path:
    path = Path(media_path)
    return path if _path_is_directory(item_type, path) else path.parent


def _candidate_nfo_paths(item_type: str, media_path: str) -> list[Path]:
    path = Path(media_path)
    is_directory = _path_is_directory(item_type, path)
    candidates: list[Path] = []
    if item_type == "series":
        candidates.append((path if is_directory else path.parent) / "tvshow.nfo")
    elif item_type == "season":
        candidates.append((path if is_directory else path.parent) / "season.nfo")
    elif item_type == "movie":
        base = path if is_directory else path.parent
        candidates.append(base / "movie.nfo")
        candidates.append(base / f"{base.name}.nfo" if is_directory else path.with_suffix(".nfo"))
    elif is_directory:
        candidates.extend([path / "tvshow.nfo", path / "movie.nfo"])
    else:
        candidates.append(path.with_suffix(".nfo"))

    seen: set[str] = set()
    result: list[Path] = []
    for candidate in candidates:
        key = str(candidate).casefold()
        if key not in seen:
            seen.add(key)
            result.append(candidate)
    return result


def _find_nfo(item_type: str, media_path: str, stored_path: str | None = None) -> Path | None:
    candidates = ([Path(stored_path)] if stored_path else []) + _candidate_nfo_paths(item_type, media_path)
    for candidate in candidates:
        try:
            if candidate.is_file():
                return candidate
        except OSError:
            continue
    return None


def _media_directory_reachable(item_type: str, media_path: str) -> bool:
    try:
        return _media_directory(item_type, media_path).is_dir()
    except OSError:
        return False
