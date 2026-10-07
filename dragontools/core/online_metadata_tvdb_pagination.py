"""Load one complete TVDB episode list without trusting provider link targets."""
from urllib.parse import parse_qs, urljoin, urlparse

from .online_metadata_types import OnlineMetadataResponseError, TVDB_API_BASE


def next_episode_page(payload, endpoint, current):
    links = payload.get('links')
    if links is None:
        return None
    if not isinstance(links, dict):
        raise OnlineMetadataResponseError('TheTVDB-Paginierung enthält ungültige Links.')
    value = links.get('next')
    if value in (None, ''):
        return None
    if not isinstance(value, str):
        raise OnlineMetadataResponseError('TheTVDB-Folgeseite ist kein gültiger Link.')
    base = urlparse(TVDB_API_BASE + endpoint)
    target = urlparse(urljoin(TVDB_API_BASE + endpoint, value))
    pages = parse_qs(target.query).get('page', [])
    if ((target.scheme, target.netloc, target.path) != (base.scheme, base.netloc, base.path)
            or len(pages) != 1 or not pages[0].isascii() or not pages[0].isdecimal()):
        raise OnlineMetadataResponseError('TheTVDB-Folgeseite gehört nicht zur angeforderten Episodenliste.')
    page = int(pages[0])
    if page <= current or page >= 1000:
        raise OnlineMetadataResponseError('TheTVDB-Paginierung wiederholt oder überschreitet gültige Seiten.')
    return page


def load_episode_pages(request, endpoint, *, force_refresh):
    from .online_metadata_tvdb_helpers import _episodes_from_tvdb_response
    episodes = []
    page = 0
    while True:
        payload = request(endpoint, {'page': page}, force_refresh=force_refresh)
        episodes.extend(_episodes_from_tvdb_response(payload))
        following = next_episode_page(payload, endpoint, page)
        if following is None:
            return episodes
        page = following
