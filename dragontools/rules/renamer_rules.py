# -*- coding: utf-8 -*-
from __future__ import annotations

import re
from copy import deepcopy
from typing import Any

from ..core.type_utils import _safe_bool, _safe_int
from .rule_loader import load_named_rules

_DEFAULT = {
    "_schema_version": 2,
    "character_replacements": [
        {"character": "*", "replacement": "X"},
        {"character": '"', "replacement": "'"},
        {"character": "'", "replacement": "`"},
        {"character": "/", "replacement": "-"},
        {"character": "\\", "replacement": "-"},
        {"character": "#", "replacement": ""},
        {"character": "?", "replacement": ""},
        {"character": "<", "replacement": ""},
        {"character": ">", "replacement": ""},
        {"character": ":", "replacement": ""},
        {"character": "|", "replacement": "."},
    ],
    "title_exceptions": [],
    "matching": {
        "minimum_candidate_score": 0.60,
        "fallback_candidate_scores": [0.45, 0.30],
        "manual_review_below": 0.72,
        "auto_accept_from": 0.78,
        "fuzzy_fallback": True,
        "retry_without_year": True,
        "fuzzy_prefix_min_words": 3,
    },
}

_RULES_CACHE: dict[str, Any] | None = None


def _clamp_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return default


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    number = _safe_int(value, default)
    return max(low, min(high, default if number is None else number))


def migrate_renamer_rules(data: dict[str, Any] | None) -> dict[str, Any]:
    raw = dict(data or {})
    result = deepcopy(_DEFAULT)

    replacements = raw.get("character_replacements")
    if isinstance(replacements, dict):
        replacements = [
            {"character": str(k), "replacement": str(v)}
            for k, v in replacements.items()
        ]
    if isinstance(replacements, list):
        cleaned = []
        seen = set()
        for item in replacements:
            if not isinstance(item, dict):
                continue
            char = str(item.get("character") or "")
            if not char or char in seen:
                continue
            seen.add(char)
            cleaned.append({
                "character": char,
                "replacement": str(item.get("replacement") or ""),
            })
        if cleaned:
            result["character_replacements"] = cleaned

    exceptions = raw.get("title_exceptions")
    if isinstance(exceptions, list):
        cleaned = []
        for item in exceptions:
            if not isinstance(item, dict):
                continue
            source = str(item.get("source") or item.get("from") or "").strip()
            target = str(item.get("replacement") or item.get("target") or item.get("to") or "").strip()
            if source and target:
                cleaned.append({"source": source, "replacement": target})
        result["title_exceptions"] = cleaned

    matching = dict(raw.get("matching") or {})
    defaults = _DEFAULT["matching"]
    raw_fallback_scores = list(matching.get("fallback_candidate_scores") or [])
    fallback_scores = [
        _clamp_float(
            raw_fallback_scores[index] if index < len(raw_fallback_scores) else default,
            default,
            0.0,
            1.0,
        )
        for index, default in enumerate(defaults["fallback_candidate_scores"])
    ]
    result["matching"] = {
        "minimum_candidate_score": _clamp_float(
            matching.get("minimum_candidate_score"), defaults["minimum_candidate_score"], 0.0, 1.0
        ),
        "fallback_candidate_scores": fallback_scores,
        "manual_review_below": _clamp_float(
            matching.get("manual_review_below"), defaults["manual_review_below"], 0.0, 1.0
        ),
        "auto_accept_from": _clamp_float(
            matching.get("auto_accept_from"), defaults["auto_accept_from"], 0.0, 1.0
        ),
        "fuzzy_fallback": _safe_bool(matching.get("fuzzy_fallback"), defaults["fuzzy_fallback"]),
        "retry_without_year": _safe_bool(matching.get("retry_without_year"), defaults["retry_without_year"]),
        "fuzzy_prefix_min_words": _clamp_int(
            matching.get("fuzzy_prefix_min_words"), defaults["fuzzy_prefix_min_words"], 2, 8
        ),
    }
    result["_schema_version"] = 2
    return result


def get_rules() -> dict[str, Any]:
    global _RULES_CACHE
    if _RULES_CACHE is None:
        _RULES_CACHE = migrate_renamer_rules(
            load_named_rules("renamer_rules", default=_DEFAULT, migrator=migrate_renamer_rules)
        )
    return _RULES_CACHE


def reload_rules() -> None:
    global _RULES_CACHE
    _RULES_CACHE = None


def character_replacements() -> tuple[tuple[str, str], ...]:
    rows = get_rules().get("character_replacements") or []
    return tuple(
        (str(row.get("character") or ""), str(row.get("replacement") or ""))
        for row in rows
        if isinstance(row, dict) and str(row.get("character") or "")
    )


def apply_character_replacements(value: str) -> str:
    text = str(value or "")
    for source, replacement in character_replacements():
        text = text.replace(source, replacement)
    return text


def sanitize_renamer_text(
    value: str,
    *,
    fallback: str = "",
    preserve_trailing_period: bool = False,
) -> str:
    """Wendet die konfigurierten Renamer-Zeichenregeln auf lokalen Namenstext an.

    Diese Funktion ist absichtlich ausserhalb von ``movie_renamer`` angesiedelt,
    damit Renamer, Preflight und Online-Metadaten exakt dieselbe lokale
    Zeichenbehandlung verwenden koennen, ohne Import-Zyklen zu erzeugen.
    """
    text = apply_character_replacements(str(value or ""))
    # Sicherheitsnetz fuer Windows-Pfade: Zeichen, die nicht von einer
    # Benutzerregel abgedeckt sind, duerfen trotzdem nicht in Dateinamen landen.
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    if not preserve_trailing_period:
        text = text.strip(".")
    return text or fallback


def _title_key(value: str) -> str:
    text = str(value or "").casefold()
    text = text.translate(str.maketrans({
        "’": "'", "‘": "'", "´": "'", "`": "'",
        "‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-",
    }))
    text = re.sub(r"[^a-z0-9äöüß]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def apply_title_exception(value: str) -> str:
    original = str(value or "").strip()
    key = _title_key(original)
    if not key:
        return original
    for row in get_rules().get("title_exceptions") or []:
        if not isinstance(row, dict):
            continue
        source = str(row.get("source") or "").strip()
        replacement = str(row.get("replacement") or "").strip()
        if source and replacement and _title_key(source) == key:
            return replacement
    return original


def matching_rules() -> dict[str, Any]:
    return dict(get_rules().get("matching") or {})


def minimum_candidate_score() -> float:
    return float(matching_rules().get("minimum_candidate_score", 0.60))




def fallback_candidate_scores() -> tuple[float, ...]:
    """Zusätzliche automatische Mindestwerte unterhalb des normalen Scores.

    Die Werte werden absteigend, ohne Duplikate und nur unterhalb des normalen
    Mindestwerts geliefert. Damit bleibt die erste Stufe immer die reguläre
    Renamer-Grenze (standardmäßig 60 %).
    """
    primary = minimum_candidate_score()
    raw = matching_rules().get("fallback_candidate_scores") or (0.45, 0.30)
    result: list[float] = []
    for value in raw:
        score = _clamp_float(value, 0.0, 0.0, 1.0)
        if score >= primary or score in result:
            continue
        result.append(score)
    return tuple(sorted(result, reverse=True))


def candidate_score_stages(*, include_all: bool = False) -> tuple[float, ...]:
    values = [minimum_candidate_score(), *fallback_candidate_scores()]
    if include_all:
        values.append(0.0)
    seen: set[float] = set()
    result: list[float] = []
    for value in values:
        score = round(max(0.0, min(1.0, float(value))), 4)
        if score not in seen:
            seen.add(score)
            result.append(score)
    return tuple(result)


def candidate_discovery_floor() -> float:
    """Lockere interne Provider-Vorauswahl für die letzte Fallback-Stufe.

    Die Provider dürfen Kandidaten nicht schon bei 40 % verwerfen, wenn der
    Renamer bewusst bis 30 % heruntergeht. Ein kleiner Puffer hält trotzdem
    vollkommen fachfremde Rohresultate aus der teureren Episodenauflösung fern.
    """
    stages = candidate_score_stages()
    lowest = min(stages) if stages else minimum_candidate_score()
    return max(0.0, lowest - 0.05)

def manual_review_below() -> float:
    return float(matching_rules().get("manual_review_below", 0.72))


def auto_accept_from() -> float:
    return float(matching_rules().get("auto_accept_from", 0.78))


def fuzzy_fallback_enabled() -> bool:
    return _safe_bool(matching_rules().get("fuzzy_fallback"), True)


def retry_without_year_enabled() -> bool:
    return _safe_bool(matching_rules().get("retry_without_year"), True)


def series_search_queries(value: str, *, include_fuzzy: bool | None = None) -> tuple[str, ...]:
    original = str(value or "").strip()
    aliased = apply_title_exception(original)
    use_fuzzy = fuzzy_fallback_enabled() if include_fuzzy is None else bool(include_fuzzy)
    min_words = int(matching_rules().get("fuzzy_prefix_min_words", 3))

    result: list[str] = []
    seen: set[str] = set()

    def add(text: str) -> None:
        cleaned = re.sub(r"\s+", " ", str(text or "")).strip(" .-_/")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)

    add(aliased)
    add(original)

    if use_fuzzy:
        # Prefix-Suchen fangen typische kleine Wortabweichungen ab, z. B.
        # "The Forsaken Saint ..." vs. "The Forsaken Saintess ...".
        for base in (aliased, original):
            words = re.findall(r"[\wÄÖÜäöüß'’-]+", base, flags=re.UNICODE)
            if len(words) <= min_words:
                continue
            lengths = []
            for n in (6, 5, 4, 3):
                if min_words <= n < len(words) and n not in lengths:
                    lengths.append(n)
            if min_words < len(words) and min_words not in lengths:
                lengths.append(min_words)
            for n in lengths:
                add(" ".join(words[:n]))

    return tuple(result)
