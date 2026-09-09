from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .paths import VIDEO_EXTENSIONS


VIDEO_SUFFIXES = {ext.casefold() for ext in VIDEO_EXTENSIONS}
EPISODE_REPLACEMENT_ARTIFACT_SUFFIXES = {".nfo", ".trickplay"}


@dataclass(frozen=True)
class EpisodeIdentity:
    series: str
    season: int
    episodes: tuple[int, ...]
    label: str


def _episode_label(season: int, episodes: tuple[int, ...]) -> str:
    if not episodes:
        return f"S{season:02d}"
    first, *rest = episodes
    return f"S{season:02d}E{first:02d}" + "".join(f"E{ep:02d}" for ep in rest)


def norm_path(path: str | os.PathLike) -> str:
    return os.path.normcase(os.path.abspath(os.fspath(path)))


def same_path(a: str | os.PathLike, b: str | os.PathLike) -> bool:
    pa = Path(a)
    pb = Path(b)
    try:
        return pa.samefile(pb)
    except OSError:
        return norm_path(pa) == norm_path(pb)


def _episode_identity_for_named_path(path: str | os.PathLike) -> EpisodeIdentity | None:
    """Parst eine SxxExx-Identität unabhängig vom Dateityp.

    Das ist absichtlich enger als eine allgemeine Sidecar-Erkennung: genutzt wird
    es nur für Artefakte, die bereits über ihren Namen eindeutig einer Episode
    zugeordnet werden können.
    """
    p = Path(path)
    try:
        from ..rules.move_rules import parse_series_match_details

        parsed = parse_series_match_details(p.name)
    except Exception:
        return None
    if not parsed:
        return None
    episodes = tuple(
        int(ep)
        for ep in (parsed.get("episodes") or [parsed.get("episode")])
        if ep is not None
    )
    if not episodes:
        return None
    try:
        season = int(parsed["season"])
    except Exception:
        return None
    series = str(parsed.get("series") or "").strip()
    return EpisodeIdentity(
        series=series,
        season=season,
        episodes=episodes,
        label=_episode_label(season, episodes),
    )


def episode_identity_for_path(path: str | os.PathLike) -> EpisodeIdentity | None:
    """Liefert die fachliche Serienidentität einer Videodatei.

    Die eigentliche SxxExx-Erkennung bleibt bewusst in ``move_rules``. Hier wird
    nur ein kleines, vergleichbares Objekt daraus gebaut, damit Move- und
    Mediathek-Code dieselbe Identität verwenden.
    """
    p = Path(path)
    if p.suffix.casefold() not in VIDEO_SUFFIXES:
        return None
    return _episode_identity_for_named_path(p)


def find_episode_identity_conflicts(dst_p: Path, src_p: Path | None = None) -> list[Path]:
    """Findet Videodateien im Zielordner mit gleicher SxxExx-Identität.

    Für Serienfolgen ist im Staffelordner die SxxExx-Kennung maßgeblich. Ein
    anderer Episodentitel oder ein anderer Container sind deshalb trotzdem ein
    Konflikt, während Mehrfachfolgen nur bei identischer Episodenliste matchen.
    """
    dst_p = Path(dst_p)
    identity = episode_identity_for_path(dst_p)
    if identity is None:
        return []
    source_path = Path(src_p) if src_p is not None else None
    conflicts: list[Path] = []
    try:
        candidates = list(dst_p.parent.iterdir())
    except OSError:
        return conflicts
    for candidate in candidates:
        if not candidate.is_file():
            continue
        if candidate.suffix.casefold() not in VIDEO_SUFFIXES:
            continue
        if source_path is not None and same_path(candidate, source_path):
            continue
        candidate_identity = episode_identity_for_path(candidate)
        if candidate_identity is None:
            continue
        if (
            candidate_identity.season == identity.season
            and candidate_identity.episodes == identity.episodes
        ):
            conflicts.append(candidate)
    return conflicts



def find_episode_replacement_artifacts(
    dst_p: Path,
    video_conflicts: list[Path],
) -> list[Path]:
    """Findet veraltete NFO-/Trickplay-Artefakte derselben Episode.

    Bei einer SxxExx-Ersetzung kann sich der Episodentitel und damit der Stem
    ändern. Deshalb reicht ein exakter Dateiname nicht aus. Es werden sowohl
    Begleiter der tatsächlich gefundenen Altvideos als auch weitere eindeutig
    nach SxxExx zuordenbare ``.nfo``-Dateien und ``.trickplay``-Ordner im selben
    Staffelordner erfasst. Andere Episoden und andere Sidecar-Typen bleiben
    unangetastet.
    """
    dst_p = Path(dst_p)
    identity = episode_identity_for_path(dst_p)
    if identity is None or not video_conflicts:
        return []

    old_stems = {Path(path).stem.casefold() for path in video_conflicts}
    artifacts: list[Path] = []
    try:
        candidates = list(dst_p.parent.iterdir())
    except OSError:
        return artifacts

    for candidate in candidates:
        suffix = candidate.suffix.casefold()
        if suffix not in EPISODE_REPLACEMENT_ARTIFACT_SUFFIXES:
            continue
        is_nfo = candidate.is_file() and suffix == ".nfo"
        is_trickplay = candidate.is_dir() and suffix == ".trickplay"
        if not (is_nfo or is_trickplay):
            continue

        same_old_stem = candidate.stem.casefold() in old_stems
        candidate_identity = _episode_identity_for_named_path(candidate)
        same_episode = bool(
            candidate_identity
            and candidate_identity.season == identity.season
            and candidate_identity.episodes == identity.episodes
        )
        if same_old_stem or same_episode:
            artifacts.append(candidate)

    return sorted(artifacts, key=lambda path: path.name.casefold())

def find_target_conflicts(dst_p: Path, src_p: Path | None = None) -> list[Path]:
    """Findet Zielkonflikte für den Verschiebevorgang.

    Für Videodateien zählt gleicher Stammname unabhängig von der Endung:
    Film.mkv kollidiert also mit Film.mp4, Film.avi usw. Serienfolgen kollidieren
    zusätzlich über gleiche SxxExx-Identität im Zielordner. Für andere Dateien
    bleibt es beim exakten Zielnamen, damit z. B. Cover/NFO nicht versehentlich
    durch einen Videomove entfernt werden.
    """
    dst_p = Path(dst_p)
    source_path = Path(src_p) if src_p is not None else None
    conflicts: list[Path] = []

    def add(candidate: Path) -> None:
        if source_path is not None and same_path(candidate, source_path):
            return
        if any(same_path(candidate, existing) for existing in conflicts):
            return
        conflicts.append(candidate)

    if dst_p.exists():
        add(dst_p)

    if dst_p.suffix.casefold() not in VIDEO_SUFFIXES:
        return conflicts

    try:
        for candidate in dst_p.parent.iterdir():
            if not candidate.is_file():
                continue
            if candidate.suffix.casefold() not in VIDEO_SUFFIXES:
                continue
            if candidate.stem.casefold() != dst_p.stem.casefold():
                continue
            add(candidate)

        for candidate in find_episode_identity_conflicts(dst_p, src_p):
            add(candidate)
    except OSError:
        return conflicts

    return conflicts


def resolve_rename_path(dst_p: Path, src_p: Path | None = None) -> Path:
    """Gibt einen freien Zielpfad mit Suffix _01, _02, ... zurück."""
    dst_p = Path(dst_p)
    if not find_target_conflicts(dst_p, src_p):
        return dst_p

    stem = dst_p.stem
    suffix = dst_p.suffix
    parent = dst_p.parent
    counter = 1
    while True:
        candidate = parent / f"{stem}_{counter:02d}{suffix}"
        if not find_target_conflicts(candidate, src_p):
            return candidate
        counter += 1
        if counter > 999:
            raise RuntimeError(f"Kein freier Dateiname gefunden für {dst_p.name}")


def format_conflict_names(conflicts: list[Path]) -> str:
    if not conflicts:
        return ""
    names = [Path(p).name for p in conflicts]
    if len(names) <= 3:
        return ", ".join(names)
    return ", ".join(names[:3]) + f" ... (+{len(names) - 3})"
