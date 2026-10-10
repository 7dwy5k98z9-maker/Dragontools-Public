"""Fresh provider catalogs for Renamer completeness; no filename guessing."""
from .online_metadata_common import OnlineMetadataAuthError, OnlineMetadataResponseError
from .online_metadata_identity import episode_number, TVDB_SEASON_FIELDS, TVDB_EPISODE_FIELDS
from .online_metadata_tmdb import TmdbClient
from .online_metadata_tvdb import TheTvdbClient
from .renamer_completeness import compare_season


class CompletenessCancelled(Exception):
    pass


class RenamerCompletenessService:
    def __init__(self, config):
        self.config = config
        self.clients = {}
        self.tvdb_catalogs = {}

    def _client(self, provider):
        if provider in self.clients:
            return self.clients[provider]
        if provider == "tmdb":
            if not self.config.tmdb_enabled or not self.config.has_tmdb_credentials:
                raise OnlineMetadataAuthError("TMDB ist nicht vollständig eingerichtet oder deaktiviert.")
            client = TmdbClient(self.config)
        elif provider == "thetvdb":
            if not self.config.tvdb_enabled or not self.config.has_tvdb_credentials:
                raise OnlineMetadataAuthError("TheTVDB ist nicht vollständig eingerichtet oder deaktiviert.")
            client = TheTvdbClient(self.config)
        else:
            raise OnlineMetadataResponseError("Unbekannte Metadatenquelle.")
        client.enable_fresh_session()
        self.clients[provider] = client
        return client

    def _tvdb_catalog(self, hit):
        if hit.provider_id in self.tvdb_catalogs:
            return self.tvdb_catalogs[hit.provider_id]
        client = self._client(hit.provider)
        records = client.series_episodes(hit.provider_id, language=self.config.language, force_refresh=True)
        catalog = {}
        for record in records:
            season = episode_number(record, TVDB_SEASON_FIELDS, minimum=0)
            number = episode_number(record, TVDB_EPISODE_FIELDS)
            if season is None or number is None:
                raise OnlineMetadataResponseError("TheTVDB liefert Folgen ohne eindeutige Staffel-/Folgenummer.")
            catalog.setdefault(season, set()).add(number)
        if not catalog:
            raise OnlineMetadataResponseError("TheTVDB liefert keine nummerierten Folgen dieser Serie.")
        self.tvdb_catalogs[hit.provider_id] = catalog
        return catalog

    def _tmdb_seasons(self, hit):
        payload = self._client(hit.provider).tv_details(hit.provider_id)
        rows = payload.get("seasons")
        if not isinstance(rows, list) or not rows:
            raise OnlineMetadataResponseError("TMDB liefert keine Staffelliste dieser Serie.")
        seasons = {}
        for row in rows:
            season = episode_number(row, ("season_number",), minimum=0)
            if season is None:
                raise OnlineMetadataResponseError("TMDB liefert eine Staffel ohne eindeutige Nummer.")
            seasons[season] = row.get("episode_count")
        return seasons

    def _tmdb_episodes(self, hit, season, count):
        payload = self._client(hit.provider).tv_season_details(
            hit.provider_id, season, language=self.config.language, force_refresh=True)
        records = payload.get("episodes")
        if not isinstance(records, list):
            raise OnlineMetadataResponseError("TMDB liefert keine gültige Folgenliste.")
        numbers = set()
        for record in records:
            number = episode_number(record, ("episode_number",))
            returned_season = episode_number(record, ("season_number",), minimum=0)
            if number is None or ("season_number" in record and returned_season != season):
                raise OnlineMetadataResponseError("TMDB liefert eine uneindeutige Folgenzuordnung.")
            numbers.add(number)
        if count is not None and count != len(numbers):
            raise OnlineMetadataResponseError("TMDB-Staffelgröße und Folgenliste stimmen nicht überein.")
        return numbers

    def check(self, target, *, cancelled=lambda: False):
        hit = target.series.hit
        self._check_cancelled(cancelled)
        if hit.provider == "thetvdb":
            catalog = self._tvdb_catalog(hit)
            seasons = set(catalog)
            expected = lambda season: catalog.get(season, set())
        else:
            catalog = self._tmdb_seasons(hit)
            seasons = set(catalog)
            expected = lambda season: self._tmdb_episodes(hit, season, catalog[season])
        observed = {season for season, _episode in target.series.present}
        requested = {target.season} if target.season is not None else seasons | observed
        results = []
        for season in sorted(requested):
            self._check_cancelled(cancelled)
            if season not in seasons:
                results.append(compare_season(target.series, season, (),
                               error="Diese Staffel wird von der gewählten Quelle nicht geführt."))
                continue
            try:
                episodes = expected(season)
            except Exception as exc:
                results.append(compare_season(target.series, season, (), error=str(exc)))
            else:
                results.append(compare_season(target.series, season, episodes))
        self._check_cancelled(cancelled)
        return tuple(results)

    @staticmethod
    def _check_cancelled(cancelled):
        if cancelled():
            raise CompletenessCancelled()
