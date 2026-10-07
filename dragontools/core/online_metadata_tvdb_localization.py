"""Language-bound TVDB translation selection, independent of record identity."""
from .lang_codes import mkv_language_tags
from .online_metadata_parsing import compare_metadata_text


def _metadata_text_value(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        values = [value.get(key) for key in ('deu', 'de', 'eng', 'en', 'name', 'title', 'overview')]
        values.extend(value.values())
    elif isinstance(value, list):
        values = value
    else:
        return ''
    return next((text for item in values if (text := _metadata_text_value(item))), '')


def _tvdb_text(record, *keys):
    return next((text for key in keys if (text := _metadata_text_value(record.get(key)))), '')


def _tvdb_language_code(value):
    raw = str(value or '').strip().lower().replace('_', '-')
    if not raw:
        return 'eng'
    base = raw.split('-', 1)[0]
    legacy, _ietf = mkv_language_tags(base)
    return legacy or base or 'eng'


def _tvdb_language_candidates(value):
    raw = str(value or '').strip().lower()
    return tuple(dict.fromkeys(code for code in (_tvdb_language_code(raw), raw, raw.split('-', 1)[0]) if code))


def _translation_language(item):
    return str(next((item.get(key) for key in ('language', 'languageCode', 'language_code', 'code') if item.get(key)), '')).strip().lower()


def _translation_list_text(items, codes, keys):
    if not isinstance(items, list):
        return ''
    for code in codes:
        for item in items:
            if isinstance(item, dict) and _translation_language(item) == code:
                text = _tvdb_text(item, *keys)
                if text:
                    return text
    return ''


def _language_map_text(mapping, codes):
    if not isinstance(mapping, dict):
        return ''
    return next((text for code in codes if (text := _metadata_text_value(mapping.get(code)))), '')


def _nested_translation_text(record, codes, fields, keys):
    for field in fields:
        value = record.get(field)
        text = _translation_list_text(value, codes, keys) or _language_map_text(value, codes)
        if text:
            return text
    return ''


def _translated_value(value, codes, keys):
    if isinstance(value, dict):
        return _language_map_text(value, codes)
    if isinstance(value, list):
        return _translation_list_text(value, codes, keys)
    return _metadata_text_value(value)


def _tvdb_localized_title(record, language):
    if not isinstance(record, dict):
        return ''
    codes = _tvdb_language_candidates(language)
    translations = record.get('translations')
    if isinstance(translations, dict):
        text = _language_map_text(translations, codes) or _nested_translation_text(
            translations, codes, ('nameTranslations', 'name_translations', 'names', 'titles', 'name', 'title'), ('name', 'title'))
        if not text and _translation_language(translations) in codes:
            text = _tvdb_text(translations, 'name', 'title')
    else:
        text = _translation_list_text(translations, codes, ('name', 'title'))
    text = text or _nested_translation_text(record, codes, ('nameTranslations', 'name_translations'), ('name', 'title'))
    text = text or _translation_list_text(record.get('aliases'), codes, ('name', 'title'))
    if text:
        return text
    translated = _translated_value(record.get('name_translated'), codes, ('name', 'title'))
    original = _metadata_text_value(record.get('name'))
    return translated if translated and compare_metadata_text(translated) != compare_metadata_text(original) else ''


def _tvdb_localized_overview(record, language):
    if not isinstance(record, dict):
        return ''
    codes = _tvdb_language_candidates(language)
    fields = ('overviewTranslations', 'overview_translations', 'overviews')
    keys = ('overview', 'text', 'value')
    translations = record.get('translations')
    text = _nested_translation_text(translations, codes, fields, keys) if isinstance(translations, dict) else _translation_list_text(translations, codes, keys)
    return (text or _nested_translation_text(record, codes, fields[:2], keys)
            or _translated_value(record.get('overview_translated'), codes, keys))
