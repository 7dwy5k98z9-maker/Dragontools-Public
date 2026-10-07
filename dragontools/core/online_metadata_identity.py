"""Provider and episode identity validation at the response boundary."""
from .online_metadata_types import OnlineMetadataResponseError
from .movie_renamer_season_override import normalize_episode_number

TVDB_SEASON_FIELDS = ('seasonNumber', 'season_number', 'airedSeason', 'officialSeasonNumber')
TVDB_EPISODE_FIELDS = ('number', 'episodeNumber', 'episode_number', 'airedEpisodeNumber', 'officialEpisodeNumber')


def provider_id(value):
    if type(value) is int:
        return value if value > 0 else None
    if isinstance(value, str) and value.strip().isascii() and value.strip().isdecimal():
        number = int(value.strip())
        return number if number > 0 else None
    return None


def episode_number(record, keys, *, minimum=1):
    value = next((record[key] for key in keys if record.get(key) is not None), None)
    try:
        return normalize_episode_number(value, minimum=minimum)
    except ValueError:
        return None


def validate_tmdb_episode(record, season, episode=None):
    for key, expected, minimum in [('season_number', season, 0), ('episode_number', episode, 1)]:
        if expected is None or key not in record:
            continue
        actual = episode_number(record, (key,), minimum=minimum)
        if actual != expected:
            raise OnlineMetadataResponseError(f'TMDB-Episodenidentität stimmt nicht: {key}={actual}, erwartet {expected}.')
