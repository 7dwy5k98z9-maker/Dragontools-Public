# -*- coding: utf-8 -*-
"""Serien-/Staffel-/Episoden-Erkennung aus Release-Dateinamen."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

# Haupt-Regex: Staffel + erste Episode + Tail
# Tail erkennt jetzt sowohl E02E03 (kein Trenner) als auch E02-E03, E02 E03
_SER_EP_RE = re.compile(r"""
    (?<!\w)
    (?:
        s\s*(?P<season>\d{1,4})[.\-_\s]*e\s*(?P<episode>\d{1,4})
            (?P<tail>(?:[eE]\d{1,4}|[-_.\s]+[eE]?\d{1,4})*)
      |
        s\s*(?P<season2>\d{1,4})\s*[x]\s*(?:e\s*)?(?P<episode2>\d{1,4})
            (?P<tail2>(?:\s*[x\-]\s*(?:e\s*)?\d{1,4})*)
      |
        (?P<season3>\d{1,4})\s*[x]\s*(?P<episode3>\d{1,4})
            (?P<tail3>(?:\s*[x\-]\s*\d{1,4})*)
    )
    (?!\d)
""", re.VERBOSE | re.IGNORECASE)

# Weitere Episoden im Tail: direkt E<zahl> oder x/- <zahl>
_MULTI_EP_E_RE = re.compile(r"[eE](\d{1,4})")
_MULTI_EP_X_RE = re.compile(r"[x\-]\s*(\d{1,4})")

_SEP_BEFORE    = re.compile(r"\s-\s*$")
_DOUBLE_BEFORE = re.compile(r"-\s*-\s*$")
_SEP_AFTER     = re.compile(r"^\s*-\s*")

def _decide_series_block(stem: str, m: re.Match) -> str:
    before = stem[:m.start()]; after = stem[m.end():]
    b = before.rstrip()
    if _DOUBLE_BEFORE.search(before):
        return _SEP_BEFORE.sub("", before).rstrip()
    has_before = bool(_SEP_BEFORE.search(before))
    has_after  = bool(_SEP_AFTER.match(after))
    if has_before and has_after:
        return _SEP_BEFORE.sub("", before).rstrip()
    return b

def _clean_series_name(s: str) -> str:
    # DragonTools patch: robust preflight series normalization v4
    s = str(s or "").strip()

    # Dekorative Trenner am Rand entfernen. Damit werden u. a.
    # "Watson -", "Watson –", "Watson /" zu "Watson".
    edge_chars = r"\s._/\\\-\u2010\u2011\u2012\u2013\u2014\u207b\u2212"
    s = re.sub(rf"^[{edge_chars}]+", "", s)
    # Klammern zunaechst erhalten: Bei "Titel (2019) - S01E01" muss erst
    # der dekorative Trenner und danach der vollstaendige Jahressuffix
    # entfernt werden. Andernfalls blieb bisher "Titel (2019" uebrig.
    s = re.sub(rf"[{edge_chars}]+$", "", s)

    s = s.replace("_", " ")
    s = re.sub(r"(?<=\w)\.(?=\w)", " ", s)
    s = re.sub(r"[.]{2,}", " ", s)
    s = re.sub(r"\s*\((19\d{2}|20\d{2})\)\s*$", "", s)
    s = re.sub(r"[\s._-]+(19\d{2}|20\d{2})\s*$", "", s)
    s = re.sub(rf"[{edge_chars}\[\](){{}}]+$", "", s)

    # Sichtbare Titeltrenner vereinheitlichen; Spider-Man bleibt unangetastet.
    s = re.sub(r"\s+-\s*", " - ", s)
    s = re.sub(r"\s*-\s+", " - ", s)
    s = re.sub(r"\s{2,}", " ", s)

    # Nach der Normalisierung erneut einen reinen Endtrenner entfernen.
    s = re.sub(r"\s*[-\u2010\u2011\u2012\u2013\u2014\u207b\u2212/\\]+\s*$", "", s)
    return s.strip()

def parse_series_match_details(filename: str) -> dict[str, Any] | None:
    stem = Path(filename).stem
    m    = _SER_EP_RE.search(stem)
    if not m:
        return None

    season_s  = m.group("season")  or m.group("season2")  or m.group("season3")
    episode_s = m.group("episode") or m.group("episode2") or m.group("episode3")
    tail      = m.group("tail")    or m.group("tail2")    or m.group("tail3") or ""
    is_x_fmt  = bool(m.group("season2") or m.group("season3"))

    season   = int(season_s)
    first_ep = int(episode_s)
    episodes = [first_ep]

    # Fix: E<zahl> direkt im Tail suchen statt nach Trennzeichen
    ep_re = _MULTI_EP_X_RE if is_x_fmt else _MULTI_EP_E_RE
    for ep_str in ep_re.findall(tail):
        ep_i = int(ep_str)
        if ep_i not in episodes:
            episodes.append(ep_i)

    series = _clean_series_name(_decide_series_block(stem, m)) or None
    return {
        "series":     series,
        "season":     season,
        "episode":    first_ep,
        "episodes":   episodes,
        "match_text": m.group(0),
    }

def parse_series_season_episode(filename: str) -> tuple[str | None, int, int] | None:
    d = parse_series_match_details(filename)
    if not d:
        return None
    return d["series"], d["season"], d["episode"]
