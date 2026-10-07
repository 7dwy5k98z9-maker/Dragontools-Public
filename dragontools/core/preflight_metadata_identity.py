"""Preserve the explicitly selected metadata edition without renaming media files."""
from copy import deepcopy
import re

from .path_syntax import user_path_name


def normalize_metadata_context(value) -> dict | None:
    if not isinstance(value, dict):
        return None
    title = str(value.get('title') or '').strip()
    kind = value.get('kind')
    year = value.get('year')
    if not title or kind not in {'series', 'movie'} or isinstance(year, bool):
        return None
    try:
        year = int(str(year))
    except (TypeError, ValueError):
        return None
    if not 1900 <= year <= 2099:
        return None
    result = {'kind': kind, 'title': title, 'year': year}
    if kind == 'series':
        try:
            season, episode = int(str(value['season'])), int(str(value['episode']))
        except (KeyError, TypeError, ValueError):
            return None
        if season < 0 or episode <= 0:
            return None
        result.update(season=season, episode=episode)
    return result


def metadata_context_for_target(path: str, target) -> dict | None:
    from .planned_target_edit import infer_series_season, series_root_from_target
    from ..rules.move_rules import parse_series_match_details, planned_target_dir
    folder = planned_target_dir(target)
    if not folder:
        return None
    root = series_root_from_target(target)
    name = user_path_name(root or folder)
    match = re.fullmatch(r'(.+?)\s*\((19\d{2}|20\d{2})\)', name.strip())
    if not match:
        return None
    value = {'kind': 'series' if root else 'movie', 'title': match[1].strip(), 'year': int(match[2])}
    if root:
        parsed = parse_series_match_details(user_path_name(path)) or {}
        value.update(season=infer_series_season(path, target), episode=parsed.get('episode'))
    return normalize_metadata_context(value)


def with_planned_metadata(overrides: dict, planned_targets: dict) -> dict:
    """Capture a separate metadata identity for each planned queue item."""
    result = deepcopy(overrides or {})
    for path, target in (planned_targets or {}).items():
        context = metadata_context_for_target(path, target)
        if context is not None:
            result.setdefault(path, {})['metadata_context'] = context
    return result


def metadata_lookup_filename(context: dict, fallback: str) -> str:
    value = normalize_metadata_context(context)
    if value is None:
        return fallback
    title = value['title'].replace('/', ' ').replace('\\', ' ')
    name = f"{title} ({value['year']})"
    if value['kind'] == 'series':
        name += f".S{value['season']:02d}E{value['episode']:02d}"
    return name + '.mkv'
