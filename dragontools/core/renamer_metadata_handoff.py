"""Keep confirmed Renamer series identities for the next destination selection.

The handoff is bounded, process-local and performs no filesystem or API reads.
Only successfully renamed files with a selected provider match are remembered.
"""
from __future__ import annotations

from collections import OrderedDict
from threading import RLock

from .movie_renamer_models import SeriesRenameProposal
from .movie_renamer_parsing import parse_series_release_name
from .online_metadata_common import SeriesMetadataSuggestion, compare_metadata_text
from .path_syntax import path_compare_key, user_path_name


class RenamerMetadataHandoff:
    def __init__(self, max_entries: int = 4096):
        self._max_entries = max(1, max_entries)
        self._entries: OrderedDict[str, SeriesMetadataSuggestion] = OrderedDict()
        self._lock = RLock()

    def remember(self, target_path: str, proposal) -> None:
        key = path_compare_key(target_path)
        with self._lock:
            self._entries.pop(key, None)
        if not isinstance(proposal, SeriesRenameProposal) or proposal.selected is None:
            return
        candidate = proposal.selected
        parsed = parse_series_release_name(user_path_name(target_path))
        if parsed is None or compare_metadata_text(parsed.series) != compare_metadata_text(candidate.series):
            return
        if candidate.provider not in {"tmdb", "thetvdb"} or not candidate.provider_id:
            return
        if parsed.year is not None and parsed.year != candidate.year:
            return
        suggestion = SeriesMetadataSuggestion(
            query_title=parsed.series, query_year=parsed.year,
            tmdb_id=candidate.provider_id, name=candidate.series,
            original_name=candidate.series, first_air_year=candidate.year,
            provider=candidate.provider, provider_id=candidate.provider_id,
        )
        with self._lock:
            self._entries[key] = suggestion
            self._entries.move_to_end(key)
            while len(self._entries) > self._max_entries:
                self._entries.popitem(last=False)

    def series_for_paths(self, paths, series_name: str, year: int | None = None):
        with self._lock:
            values = [self._entries.get(path_compare_key(path)) for path in paths]
        if not values or any(value is None for value in values):
            return None
        first = values[0]
        if any(value != first for value in values):
            return None
        if compare_metadata_text(first.query_title) != compare_metadata_text(series_name):
            return None
        if year is not None and first.first_air_year != year:
            return None
        return first


_HANDOFF = RenamerMetadataHandoff()


def remember_renamed_series(target_path: str, proposal) -> None:
    _HANDOFF.remember(target_path, proposal)


def known_series_for_entries(entries, series_name: str, year: int | None = None):
    return _HANDOFF.series_for_paths((entry.get("path", "") for entry in entries), series_name, year)
