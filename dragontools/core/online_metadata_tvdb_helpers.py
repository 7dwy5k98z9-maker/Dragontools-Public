# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from typing import Any

from .online_metadata_common import (
    _int_or_none,
    _year_from_date,
    compare_metadata_text,
    normalize_episode_metadata_title,
)

def _records_from_data(data: dict[str, Any]) -> list[dict[str, Any]]:
    records = data.get("data") if isinstance(data, dict) else []
    if isinstance(records, dict):
        records = records.get("results") or records.get("items") or []
    if not isinstance(records, list):
        return []
    return [dict(item) for item in records if isinstance(item, dict)]


def _single_record_from_data(data: dict[str, Any]) -> dict[str, Any] | None:
    record = data.get("data") if isinstance(data, dict) else None
    return dict(record) if isinstance(record, dict) else None


def _episodes_from_tvdb_response(data: dict[str, Any]) -> list[dict[str, Any]]:
    payload = data.get("data") if isinstance(data, dict) else None
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        episodes = payload.get("episodes") or payload.get("data") or []
        if isinstance(episodes, list):
            return [dict(item) for item in episodes if isinstance(item, dict)]
    return []


def _tvdb_record_id(record: dict[str, Any]) -> int | None:
    for key in ("provider_id", "tvdb_id", "tvdbId", "id", "movieId", "seriesId", "objectID", "object_id"):
        value = record.get(key)
        numeric = _int_or_none(value)
        if numeric is not None:
            return numeric
        match = re.search(r"(\d+)$", str(value or ""))
        if match:
            return int(match.group(1))
    return None


def _tvdb_remote_id(record: dict[str, Any], provider: str) -> str:
    wanted = str(provider or "").strip().lower()
    for key in ("remoteIds", "remote_ids"):
        remote_ids = record.get(key)
        if not isinstance(remote_ids, list):
            continue
        for item in remote_ids:
            if not isinstance(item, dict):
                continue
            source = str(
                item.get("sourceName")
                or item.get("source")
                or item.get("type")
                or item.get("provider")
                or ""
            ).lower()
            if wanted and wanted not in source:
                continue
            remote_id = str(item.get("id") or item.get("remoteId") or item.get("remote_id") or "").strip()
            if remote_id:
                return remote_id
    return ""


def _tvdb_language_candidates(value: str) -> tuple[str, ...]:
    raw = str(value or "").strip().lower()
    tvdb = _tvdb_language_code(raw)
    short = raw.split("-", 1)[0] if raw else ""
    values: list[str] = []
    for candidate in (tvdb, raw, short):
        if candidate and candidate not in values:
            values.append(candidate)
    return tuple(values)


def _tvdb_localized_title(record: dict[str, Any], language: str) -> str:
    """Liest den Titel in der gewünschten TheTVDB-Sprache.

    TheTVDB v4 liefert je nach Endpoint mehrere Formen:
    - SearchResult: ``name_translated`` und teils ``translations`` als Sprach-Dict
    - ``extended?meta=translations``: ``translations.nameTranslations`` als
      Liste von Translation-Records (``language`` + ``name``)
    - ältere/abweichende Antworten mit verschachtelten Dicts.

    Exakte Sprachübersetzungen werden immer vor Originaltitel/Alias-Fallbacks
    bevorzugt. Dadurch überschreibt z.B. ein japanischer Originaltitel nicht
    mehr einen vorhandenen deutschen/englischen Namen.
    """
    if not isinstance(record, dict):
        return ""
    candidates = _tvdb_language_candidates(language)

    def from_translation_list(items: Any) -> str:
        if not isinstance(items, list):
            return ""
        for code in candidates:
            for item in items:
                if not isinstance(item, dict):
                    continue
                lang = str(
                    item.get("language")
                    or item.get("languageCode")
                    or item.get("language_code")
                    or item.get("code")
                    or ""
                ).strip().lower()
                if lang != code:
                    continue
                text = _tvdb_text(item, "name", "title")
                if text:
                    return text
        return ""

    translations = record.get("translations")
    if isinstance(translations, dict):
        # Search-/Simple-Form: {"eng": "Title", "deu": "Titel"}
        for code in candidates:
            text = _metadata_text_value(translations.get(code))
            if text:
                return text

        # Offizielle TranslationExtended-Form:
        # {"nameTranslations": [{"language": "eng", "name": "..."}, ...]}
        for key in (
            "nameTranslations",
            "name_translations",
            "names",
            "titles",
            "name",
            "title",
        ):
            nested = translations.get(key)
            text = from_translation_list(nested)
            if text:
                return text
            if isinstance(nested, dict):
                for code in candidates:
                    text = _metadata_text_value(nested.get(code))
                    if text:
                        return text

        # Einzelner Translation-Record als Dict.
        lang = str(
            translations.get("language")
            or translations.get("languageCode")
            or translations.get("language_code")
            or ""
        ).strip().lower()
        if lang in candidates:
            text = _tvdb_text(translations, "name", "title")
            if text:
                return text

    text = from_translation_list(translations)
    if text:
        return text

    # Manche Antworten führen Übersetzungen direkt als Sprach-Dict.
    for key in ("nameTranslations", "name_translations"):
        value = record.get(key)
        if isinstance(value, dict):
            for code in candidates:
                text = _metadata_text_value(value.get(code))
                if text:
                    return text
        # Eine Liste aus Strings bedeutet bei TVDB normalerweise nur
        # "für diese Sprachen existiert eine Übersetzung" und enthält keinen
        # Titeltext; sie darf deshalb nicht als Titel verwendet werden.

    # Sprachgebundene Aliase sind besser als ein fremdsprachiger Originaltitel.
    aliases = record.get("aliases")
    if isinstance(aliases, list):
        for code in candidates:
            for alias in aliases:
                if not isinstance(alias, dict):
                    continue
                lang = str(
                    alias.get("language")
                    or alias.get("languageCode")
                    or alias.get("language_code")
                    or ""
                ).strip().lower()
                if lang == code:
                    text = _tvdb_text(alias, "name", "title")
                    if text:
                        return text

    # SearchResult: vom Search-Endpoint für die angeforderte Sprache
    # berechneter Titel. Erst nach expliziten Translation-Records nutzen.
    translated = _metadata_text_value(record.get("name_translated"))
    original = _metadata_text_value(record.get("name"))
    # Wenn TheTVDB mangels Übersetzung lediglich den Originaltitel nochmals
    # als name_translated liefert, behandeln wir das nicht als erfolgreiche
    # Lokalisierung. So kann die konfigurierte Fallback-Sprache noch greifen.
    if translated and compare_metadata_text(translated) != compare_metadata_text(original):
        return translated
    return ""

def _tvdb_text(record: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = record.get(key)
        text = _metadata_text_value(value)
        if text:
            return text
    return ""


def _metadata_text_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in ("deu", "de", "eng", "en", "name", "title", "overview"):
            text = _metadata_text_value(value.get(key))
            if text:
                return text
        for item in value.values():
            text = _metadata_text_value(item)
            if text:
                return text
    if isinstance(value, list):
        for item in value:
            text = _metadata_text_value(item)
            if text:
                return text
    return ""


def _tvdb_language_code(value: str) -> str:
    code = str(value or "").strip().lower()
    mapping = {
        "de": "deu",
        "de-de": "deu",
        "ger": "deu",
        "deu": "deu",
        "en": "eng",
        "en-us": "eng",
        "en-gb": "eng",
        "eng": "eng",
        "ja": "jpn",
        "ja-jp": "jpn",
        "jpn": "jpn",
        "fr": "fra",
        "fr-fr": "fra",
        "fre": "fra",
        "fra": "fra",
    }
    return mapping.get(code, code[:3] if len(code) >= 3 else code or "eng")


def _year_from_tvdb_record(record: dict[str, Any]) -> int | None:
    for key in ("year", "firstAired", "first_air_date", "releaseDate", "aired"):
        year = _year_from_date(record.get(key))
        if year:
            return year
    return None


def _episode_title_is_fallback(
    record: dict[str, Any] | None,
    episode: int,
    *,
    source_path: Any = None,
) -> bool:
    if not isinstance(record, dict):
        return True
    _title, is_fallback = normalize_episode_metadata_title(
        _tvdb_text(record, "name_translated", "name", "title"),
        episode,
        source_path=source_path,
    )
    return is_fallback


def _merge_episode_language_fallback(
    primary: dict[str, Any],
    fallback: dict[str, Any],
    episode: int,
) -> dict[str, Any]:
    """Keep localized primary metadata but take a real title from fallback."""
    merged = dict(fallback or {})
    for key, value in (primary or {}).items():
        if value not in (None, "", [], {}):
            merged[key] = value
    fallback_title, fallback_is_generic = normalize_episode_metadata_title(
        _tvdb_text(fallback or {}, "name_translated", "name", "title"),
        episode,
    )
    if not fallback_is_generic:
        merged["name_translated"] = fallback_title
        merged["name"] = fallback_title
        merged["title"] = fallback_title
    return merged
