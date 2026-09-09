# -*- coding: utf-8 -*-
"""
dragontools/core/lang_codes.py

Gemeinsame Sprachcode- und Subtitle-Codec-Tabellen.

Vorher waren diese Daten dreifach dupliziert:
  - worker/dv_remux_thread.py  LANG_CODES dict (Modulebene)
  - ältere DV-Pipeline-Implementierung: lokale lang_map-Dicts

Oeffentliche API
----------------
LANG_MAP : dict[str, str]
    ISO-639-1/2-Codes -> lesbare Sprachbezeichnung.
    Beispiel: LANG_MAP["de"] == "Deutsch"

lang_display(code) -> str
    Gibt den lesbaren Namen zurück; unbekannte Codes unverändert.

sub_codec_to_ext_and_args(codec) -> tuple[str, list[str]] | None
    Gibt (Dateiendung, ffmpeg-Codec-Args) für einen bekannten
    Untertitel-Codec zurück, oder None für unbekannte Codecs.
    Beispiel: sub_codec_to_ext_and_args("subrip") == (".srt", ["-c:s", "srt"])
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Sprachcode-Tabelle
# ---------------------------------------------------------------------------

LANGUAGE_CHOICES: tuple[tuple[str, str], ...] = (
    ("de", "Deutsch"),
    ("en", "Englisch"),
    ("ja", "Japanisch"),
    ("fr", "Französisch"),
    ("es", "Spanisch"),
    ("it", "Italienisch"),
    ("ko", "Koreanisch"),
    ("zh", "Chinesisch"),
    ("pt", "Portugiesisch"),
    ("ru", "Russisch"),
    ("pl", "Polnisch"),
    ("nl", "Niederländisch"),
    ("sv", "Schwedisch"),
    ("no", "Norwegisch"),
    ("da", "Dänisch"),
    ("fi", "Finnisch"),
    ("tr", "Türkisch"),
    ("cs", "Tschechisch"),
    ("hu", "Ungarisch"),
    ("el", "Griechisch"),
    ("ar", "Arabisch"),
)


LANG_MAP: dict[str, str] = {
    code: name for code, name in LANGUAGE_CHOICES
}
LANG_MAP.update({
    "deu": "Deutsch",
    "ger": "Deutsch",
    "eng": "Englisch",
    "jpn": "Japanisch",
    "fra": "Französisch",
    "fre": "Französisch",
    "spa": "Spanisch",
    "ita": "Italienisch",
    "kor": "Koreanisch",
    "zho": "Chinesisch",
    "chi": "Chinesisch",
    "por": "Portugiesisch",
    "rus": "Russisch",
    "pol": "Polnisch",
    "nld": "Niederländisch",
    "dut": "Niederländisch",
    "swe": "Schwedisch",
    "nor": "Norwegisch",
    "dan": "Dänisch",
    "fin": "Finnisch",
    "tur": "Türkisch",
    "ces": "Tschechisch",
    "cze": "Tschechisch",
    "hun": "Ungarisch",
    "ell": "Griechisch",
    "gre": "Griechisch",
    "ara": "Arabisch",
})


def lang_display(code: str) -> str:
    """Gibt den lesbaren Sprachnamen für *code* zurück.

    Unbekannte Codes werden unverändert zurückgegeben (kein KeyError).
    """
    return LANG_MAP.get((code or "").lower(), code or "und")


# ---------------------------------------------------------------------------
# ISO 639-2 → ISO 639-1 Konvertierung (für Jellyfin/VLC-konforme Dateinamen)
# ---------------------------------------------------------------------------

_ISO_639_2_TO_1: dict[str, str] = {
    "aar": "aa", "abk": "ab", "afr": "af", "aka": "ak", "amh": "am",
    "ara": "ar", "arg": "an", "asm": "as", "ava": "av", "ave": "ae",
    "aym": "ay", "aze": "az", "bak": "ba", "bam": "bm", "bel": "be",
    "ben": "bn", "bis": "bi", "bod": "bo", "bos": "bs", "bre": "br",
    "bul": "bg", "cat": "ca", "ces": "cs", "cze": "cs", "cha": "ch",
    "che": "ce", "chu": "cu", "chv": "cv", "cor": "kw", "cos": "co",
    "cre": "cr", "cym": "cy", "dan": "da", "deu": "de", "ger": "de",
    "div": "dv", "dzo": "dz", "ell": "el", "gre": "el", "eng": "en",
    "epo": "eo", "est": "et", "eus": "eu", "baq": "eu", "ewe": "ee",
    "fao": "fo", "fas": "fa", "per": "fa", "fij": "fj", "fin": "fi",
    "fra": "fr", "fre": "fr", "fry": "fy", "ful": "ff", "gla": "gd",
    "gle": "ga", "glg": "gl", "glv": "gv", "grn": "gn", "guj": "gu",
    "hat": "ht", "hau": "ha", "heb": "he", "her": "hz", "hin": "hi",
    "hmo": "ho", "hrv": "hr", "hun": "hu", "hye": "hy", "arm": "hy",
    "ibo": "ig", "ido": "io", "iii": "ii", "iku": "iu", "ile": "ie",
    "ina": "ia", "ind": "id", "ipk": "ik", "isl": "is", "ice": "is",
    "ita": "it", "jav": "jv", "jpn": "ja", "kal": "kl", "kan": "kn",
    "kas": "ks", "kat": "ka", "geo": "ka", "kau": "kr", "kaz": "kk",
    "khm": "km", "kik": "ki", "kin": "rw", "kir": "ky", "kom": "kv",
    "kon": "kg", "kor": "ko", "kua": "kj", "kur": "ku", "lao": "lo",
    "lat": "la", "lav": "lv", "lim": "li", "lin": "ln", "lit": "lt",
    "lub": "lu", "lug": "lg", "mah": "mh", "mal": "ml", "mar": "mr",
    "mkd": "mk", "mac": "mk", "mlg": "mg", "mlt": "mt", "mon": "mn",
    "mri": "mi", "mao": "mi", "msa": "ms", "may": "ms", "mya": "my",
    "bur": "my", "nau": "na", "nav": "nv", "nbl": "nr", "nde": "nd",
    "ndo": "ng", "nep": "ne", "nld": "nl", "dut": "nl", "nno": "nn",
    "nob": "nb", "nor": "no", "nya": "ny", "oci": "oc", "oji": "oj",
    "ori": "or", "orm": "om", "oss": "os", "pan": "pa", "pli": "pi",
    "pol": "pl", "por": "pt", "pus": "ps", "que": "qu", "roh": "rm",
    "ron": "ro", "rum": "ro", "run": "rn", "rus": "ru", "sag": "sg",
    "san": "sa", "sin": "si", "slk": "sk", "slo": "sk", "slv": "sl",
    "sme": "se", "smo": "sm", "sna": "sn", "snd": "sd", "som": "so",
    "sot": "st", "spa": "es", "sqi": "sq", "alb": "sq", "srd": "sc",
    "srp": "sr", "ssw": "ss", "sun": "su", "swa": "sw", "swe": "sv",
    "tah": "ty", "tam": "ta", "tat": "tt", "tel": "te", "tgk": "tg",
    "tgl": "tl", "tha": "th", "tir": "ti", "ton": "to", "tsn": "tn",
    "tso": "ts", "tuk": "tk", "tur": "tr", "twi": "tw", "uig": "ug",
    "ukr": "uk", "urd": "ur", "uzb": "uz", "ven": "ve", "vie": "vi",
    "vol": "vo", "wln": "wa", "wol": "wo", "xho": "xh", "yid": "yi",
    "yor": "yo", "zha": "za", "zho": "zh", "chi": "zh", "zul": "zu",
}


def lang_iso_tag(code: str) -> str:
    """Konvertiert einen ISO-639-2-Code in ISO-639-1 (2-stellig), falls bekannt.

    Bekannte 2-stellige Codes werden unverändert zurückgegeben.
    Unbekannte Codes werden unverändert zurückgegeben (kein Fehler).
    Leere/None-Eingaben ergeben 'und'.

    Wird für Jellyfin/VLC-konforme Untertitel-Dateinamen verwendet:
        Film.deu.srt → Film.de.srt

    Beispiele:
        lang_iso_tag("deu") -> "de"
        lang_iso_tag("eng") -> "en"
        lang_iso_tag("jpn") -> "ja"
        lang_iso_tag("de")  -> "de"   (bereits 2-stellig)
        lang_iso_tag(None)  -> "und"
    """
    cleaned = (code or "").strip().lower()
    if not cleaned:
        return "und"
    return _ISO_639_2_TO_1.get(cleaned, cleaned)


_LANGUAGE_ALIASES_BY_CODE: dict[str, set[str]] = {
    "de": {"de", "deu", "ger", "deutsch", "german"},
    "en": {"en", "eng", "englisch", "english"},
    "ja": {"ja", "jpn", "japanese", "japanisch"},
    "fr": {"fr", "fra", "fre", "franzoesisch", "französisch", "french"},
    "es": {"es", "spa", "spanisch", "spanish"},
    "it": {"it", "ita", "italienisch", "italian"},
    "ko": {"ko", "kor", "koreanisch", "korean"},
    "zh": {"zh", "zho", "chi", "chinesisch", "chinese"},
    "pt": {"pt", "por", "portugiesisch", "portuguese"},
    "ru": {"ru", "rus", "russisch", "russian"},
    "pl": {"pl", "pol", "polnisch", "polish"},
    "nl": {"nl", "nld", "dut", "niederlaendisch", "niederländisch", "dutch"},
    "sv": {"sv", "swe", "schwedisch", "swedish"},
    "no": {"no", "nor", "norwegisch", "norwegian"},
    "da": {"da", "dan", "daenisch", "dänisch", "danish"},
    "fi": {"fi", "fin", "finnisch", "finnish"},
    "tr": {"tr", "tur", "tuerkisch", "türkisch", "turkish"},
    "cs": {"cs", "ces", "cze", "tschechisch", "czech"},
    "hu": {"hu", "hun", "ungarisch", "hungarian"},
    "el": {"el", "ell", "gre", "griechisch", "greek"},
    "ar": {"ar", "ara", "arabisch", "arabic"},
}

for _iso3, _iso1 in _ISO_639_2_TO_1.items():
    _LANGUAGE_ALIASES_BY_CODE.setdefault(_iso1, {_iso1}).add(_iso3)

_LANGUAGE_ALIAS_TO_CODE: dict[str, str] = {}
for _code, _aliases in _LANGUAGE_ALIASES_BY_CODE.items():
    _LANGUAGE_ALIAS_TO_CODE[_code] = _code
    for _alias in _aliases:
        _LANGUAGE_ALIAS_TO_CODE[_alias.lower()] = _code


def _clean_language_token(value: str | None) -> str:
    cleaned = (value or "").strip().lower()
    if "(" in cleaned and ")" in cleaned:
        inner = cleaned.rsplit("(", 1)[-1].split(")", 1)[0].strip()
        if inner:
            cleaned = inner
    return cleaned


def canonical_lang(code: str | None) -> str:
    """Normalisiert Spracheingaben auf einen bevorzugten ISO-639-1-Code."""
    cleaned = _clean_language_token(code)
    if not cleaned:
        return ""
    if cleaned in _LANGUAGE_ALIAS_TO_CODE:
        return _LANGUAGE_ALIAS_TO_CODE[cleaned]
    iso1 = lang_iso_tag(cleaned)
    return _LANGUAGE_ALIAS_TO_CODE.get(iso1, iso1)


def language_aliases(code: str | None) -> set[str]:
    """Alle bekannten Schreibweisen für eine Sprache."""
    canonical = canonical_lang(code)
    if not canonical:
        return set()
    aliases = set(_LANGUAGE_ALIASES_BY_CODE.get(canonical, {canonical}))
    aliases.add(canonical)
    return aliases


def language_matches(stream_language: str | None, wanted_language: str | None) -> bool:
    """Prüft ISO-639-1/2- und Namensvarianten einer Sprache."""
    stream_clean = _clean_language_token(stream_language)
    wanted = canonical_lang(wanted_language)
    if not stream_clean or not wanted:
        return False
    return stream_clean in language_aliases(wanted) or canonical_lang(stream_clean) == wanted


def normalize_language_priority(values) -> list[str]:
    """Macht aus Codes/Namen eine eindeutige Prioritätsliste."""
    if isinstance(values, str):
        raw_values = [
            part.strip()
            for chunk in values.replace(";", "\n").splitlines()
            for part in chunk.split(",")
        ]
    elif isinstance(values, (list, tuple, set)):
        raw_values = list(values)
    else:
        raw_values = []

    result: list[str] = []
    seen: set[str] = set()
    for value in raw_values:
        code = canonical_lang(str(value))
        if not code or code in seen:
            continue
        result.append(code)
        seen.add(code)
    return result


# ---------------------------------------------------------------------------
# Subtitle-Codec-Hilfsfunktion
# ---------------------------------------------------------------------------

# Interne Tabelle: codec_name -> (extension, ffmpeg_codec_args)
_SUB_CODEC_TABLE: dict[str, tuple[str, list[str]]] = {
    "subrip":            (".srt",  ["-c:s", "srt"]),
    "srt":               (".srt",  ["-c:s", "srt"]),
    "ass":               (".ass",  ["-c:s", "ass"]),
    "ssa":               (".ass",  ["-c:s", "ass"]),
    "subt":              (".srt",  ["-c:s", "srt"]),   # MP4 "Text subtitles with various tags"
    "mov_text":          (".srt",  ["-c:s", "srt"]),   # ffprobe-Name für denselben Typ
    "tx3g":              (".srt",  ["-c:s", "srt"]),
    "text":              (".srt",  ["-c:s", "srt"]),
    "webvtt":            (".vtt",  ["-c:s", "webvtt"]),
    "hdmv_pgs_subtitle": (".sup",  ["-c:s", "copy"]),
    "dvd_subtitle":      (".mks",  ["-c:s", "copy"]),
    "vobsub":            (".mks",  ["-c:s", "copy"]),
}


def sub_codec_to_ext_and_args(codec: str) -> "tuple[str, list[str]] | None":
    """Gibt (Dateiendung, ffmpeg-Codec-Argumente) für *codec* zurück.

    Gibt None zurück wenn der Codec nicht unterstützt wird (statt einer
    leeren Liste oder eines Exceptions).  Der Aufrufer soll dann die Spur
    überspringen und ein entsprechendes Warn-Log ausgeben.

    Beispiele
    ---------
    sub_codec_to_ext_and_args("subrip")
        -> (".srt", ["-c:s", "srt"])

    sub_codec_to_ext_and_args("hdmv_pgs_subtitle")
        -> (".sup", ["-c:s", "copy"])

    sub_codec_to_ext_and_args("unbekannt")
        -> None
    """
    return _SUB_CODEC_TABLE.get((codec or "").lower())
