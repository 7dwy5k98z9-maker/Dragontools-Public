"""Conservative language and episode matching for subtitle injection."""
from __future__ import annotations

import re
from pathlib import Path

from .formats import SUBTITLE_SIDECAR_EXTENSIONS

_EPISODE = re.compile(r"(?i)(?<![a-z0-9])(?:s(\d{1,3})[ ._-]*e(\d{1,3})|(\d{1,3})x(\d{1,3}))(?!\d)")


def _normalize(name: str) -> str:
    return re.sub(r"[\W_]+", " ", name.casefold()).strip()


def _episode(name: str):
    matches = list(_EPISODE.finditer(name))
    if len(matches) != 1:
        return None
    match = matches[0]
    season, episode = (match.group(1), match.group(2)) if match.group(1) else (match.group(3), match.group(4))
    return int(season), int(episode), _normalize(name[:match.start()])


def _is_vobsub_data_file_with_index(path: Path) -> bool:
    """Do not select the .sub half of an .idx/.sub VobSub pair separately."""
    return path.suffix.casefold() == ".sub" and path.with_suffix(".idx").is_file()


def find_injection_subtitle(video_path: str | Path, language: str = "deu") -> Path:
    """Prefer a matching basename; otherwise require matching series and episode.

    Never choose arbitrarily between multiple candidates. Search only the
    video's own directory, using a dot-delimited language token.  All supported
    subtitle sidecar families are considered; a VobSub ``.idx/.sub`` pair is
    represented by its ``.idx`` control file so it is not reported twice.
    """
    video = Path(video_path)
    codes = "de|deu|ger" if language in {"de", "deu", "ger"} else "en|eng"
    language_token = re.compile(rf"(?i)\.(?:{codes})(?=[._ -]|$)")
    exact, episodes = [], []
    video_episode = _episode(video.stem)
    for candidate in sorted(video.parent.iterdir(), key=lambda p: p.name.casefold()):
        if (
            not candidate.is_file()
            or candidate.suffix.casefold() not in SUBTITLE_SIDECAR_EXTENSIONS
            or _is_vobsub_data_file_with_index(candidate)
        ):
            continue
        token = language_token.search(candidate.stem)
        if token is None:
            continue
        basename = candidate.stem[:token.start()]
        if _normalize(basename) == _normalize(video.stem):
            exact.append(candidate)
            continue
        sub_episode = _episode(basename)
        if video_episode and sub_episode and video_episode == sub_episode:
            episodes.append(candidate)
    matches = exact or episodes
    if not matches:
        raise ValueError(f"Keine passenden Untertitel für {video.name} ({language}) gefunden.")
    if len(matches) > 1:
        raise ValueError("Mehrere passende Untertitel: " + ", ".join(p.name for p in matches) + ". Bitte eine Datei auswählen.")
    return matches[0]
