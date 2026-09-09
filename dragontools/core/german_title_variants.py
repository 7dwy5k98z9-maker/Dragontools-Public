# -*- coding: utf-8 -*-
from __future__ import annotations

import re


_CONSONANTS = "bcdfghjklmnpqrstvwxyz"
_UMLAUT_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(rf"ae(?=[{_CONSONANTS}])", re.IGNORECASE), "ä"),
    (re.compile(rf"oe(?=[{_CONSONANTS}])", re.IGNORECASE), "ö"),
    (re.compile(rf"(?<!q)ue(?=[{_CONSONANTS}])", re.IGNORECASE), "ü"),
)


def german_umlaut_search_variants(value: str, *, max_variants: int = 8) -> tuple[str, ...]:
    """Erzeugt vorsichtige TMDB-Suchvarianten fuer deutsche ASCII-Umlaute.

    Release-Namen schreiben deutsche Titel oft als ``Muenchen`` oder
    ``Kinderfluesterer``. TMDB fuehrt dieselben Titel meist mit echten
    Umlauten. Die Originalschreibweise bleibt immer erste Suchanfrage; die
    Varianten werden nur als Fallback genutzt.
    """
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ()

    variants: list[str] = [text]
    seen = {text.casefold()}
    for pattern, replacement in _UMLAUT_RULES:
        for candidate in list(variants):
            converted = pattern.sub(
                lambda match: _preserve_case(replacement, match.group(0)),
                candidate,
            )
            key = converted.casefold()
            if converted and key not in seen:
                seen.add(key)
                variants.append(converted)
            if len(variants) >= max(1, int(max_variants)):
                return tuple(variants)
    return tuple(variants)


def fold_german_umlauts(value: str) -> str:
    """Macht echte Umlaute und ASCII-Umschreibungen vergleichbar."""
    text = str(value or "").casefold()
    return (
        text.replace("ä", "ae")
        .replace("ö", "oe")
        .replace("ü", "ue")
        .replace("ß", "ss")
    )


def _preserve_case(replacement: str, matched: str) -> str:
    if matched.isupper() or (matched[:1].isupper() and matched[1:].islower()):
        return replacement.upper()
    return replacement
