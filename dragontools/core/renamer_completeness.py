"""Recognized Renamer inventory and exact episode-set comparison."""
from dataclasses import dataclass

from .movie_renamer_models import SeriesRenameProposal
from .online_metadata_identity import provider_id, episode_number
from .renamer_metadata_browser import MetadataBrowserHit


@dataclass(frozen=True)
class RecognizedSeries:
    hit: MetadataBrowserHit
    present: frozenset[tuple[int, int]]


@dataclass(frozen=True)
class CompletenessTarget:
    series: RecognizedSeries
    season: int | None = None

    @property
    def label(self):
        scope = "Serie" if self.season is None else season_label(self.season)
        hit = self.series.hit
        return f"{hit.display_title} – {scope} · {hit.provider_label} (ID {hit.provider_id})"


@dataclass(frozen=True)
class CompletenessResult:
    hit: MetadataBrowserHit
    season: int | None
    status: str
    expected: tuple[int, ...] = ()
    present: tuple[int, ...] = ()
    missing: tuple[int, ...] = ()
    extra: tuple[int, ...] = ()
    note: str = ""


def season_label(season):
    return "Specials (Staffel 0)" if season == 0 else f"Staffel {season}"


def _recognized_candidate(proposal):
    if not isinstance(proposal, SeriesRenameProposal) or proposal.selected is None:
        return None
    candidate = proposal.selected
    identity = provider_id(candidate.provider_id)
    if candidate.provider not in {"tmdb", "thetvdb"} or identity is None:
        return None
    season = episode_number({"season": candidate.season}, ("season",), minimum=0)
    if season is None or not candidate.series.strip():
        return None
    episodes = {episode_number({"episode": number}, ("episode",))
                for number in candidate.episode_numbers}
    if None in episodes or not episodes:
        return None
    hit = MetadataBrowserHit("series", candidate.provider, identity, candidate.series, year=candidate.year)
    return hit, {(season, number) for number in episodes}


def recognized_series(proposals) -> tuple[RecognizedSeries, ...]:
    grouped = {}
    for proposal in proposals:
        recognized = _recognized_candidate(proposal)
        if recognized is None:
            continue
        hit, episodes = recognized
        key = (hit.provider, hit.provider_id)
        if key not in grouped:
            grouped[key] = (hit, set())
        grouped[key][1].update(episodes)
    return tuple(RecognizedSeries(hit, frozenset(episodes))
                 for hit, episodes in sorted(grouped.values(), key=lambda row: (
                     row[0].title.casefold(), row[0].provider, row[0].provider_id)))


def completeness_targets(series, *, whole_series=False) -> tuple[CompletenessTarget, ...]:
    if whole_series:
        return tuple(CompletenessTarget(item) for item in series)
    return tuple(CompletenessTarget(item, season) for item in series
                 for season in sorted({season for season, _episode in item.present}))


def compare_season(series, season, expected, *, error="") -> CompletenessResult:
    present = {episode for observed_season, episode in series.present if observed_season == season}
    expected = set(expected)
    if error or not expected:
        return CompletenessResult(series.hit, season, "Nicht prüfbar", present=tuple(sorted(present)),
                                  note=error or "Die Quelle führt keine nummerierten Folgen dieser Staffel.")
    missing = expected - present
    status = "Vollständig"
    if missing:
        status = "Staffel fehlt" if not present else "Unvollständig"
    return CompletenessResult(series.hit, season, status, tuple(sorted(expected)),
                              tuple(sorted(present & expected)), tuple(sorted(missing)),
                              tuple(sorted(present - expected)))
