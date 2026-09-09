# -*- coding: utf-8 -*-
"""Provider-Payload-Helfer für Credits, Tags, Zertifikate und Trailer."""
from __future__ import annotations

import re
from typing import Any

def _year_from_date(value: Any) -> int | None:
    text = str(value or "")
    m = re.match(r"(19\d{2}|20\d{2})", text)
    return int(m.group(1)) if m else None


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _float_or_none(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _names_from_dicts(items: Any, *, key: str = "name", limit: int | None = None) -> list[str]:
    if not isinstance(items, list):
        return []
    names: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        text = str(item.get(key) or "").strip()
        if text and text not in names:
            names.append(text)
        if limit and len(names) >= limit:
            break
    return names


def _credit_names(credits: Any, job_names: set[str]) -> list[str]:
    crew = []
    if isinstance(credits, dict):
        crew = credits.get("crew") or []
    elif isinstance(credits, list):
        crew = credits
    names: list[str] = []
    for item in crew:
        if not isinstance(item, dict):
            continue
        job = str(item.get("job") or "").strip()
        if job not in job_names:
            continue
        name = str(item.get("name") or "").strip()
        if name and name not in names:
            names.append(name)
    return names


def _actors_from_credits(credits: Any, *, limit: int = 20) -> list[dict[str, Any]]:
    cast = (credits or {}).get("cast") if isinstance(credits, dict) else []
    if not isinstance(cast, list):
        return []
    actors: list[dict[str, Any]] = []
    for item in cast:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        actors.append(
            {
                "name": name,
                "role": str(item.get("character") or "").strip(),
                "sortorder": _int_or_none(item.get("order")) or len(actors),
            }
        )
        if len(actors) >= limit:
            break
    return actors


def _movie_tags(details: dict[str, Any]) -> list[str]:
    keywords = details.get("keywords") or {}
    values = keywords.get("keywords") if isinstance(keywords, dict) else []
    return _names_from_dicts(values, key="name", limit=30)


def _certification_from_release_dates(details: dict[str, Any]) -> str:
    release_dates = details.get("release_dates") or {}
    results = release_dates.get("results") if isinstance(release_dates, dict) else []
    if not isinstance(results, list):
        return ""
    preferred = ("DE", "US")
    by_country = {str(item.get("iso_3166_1") or ""): item for item in results if isinstance(item, dict)}
    ordered = [by_country[c] for c in preferred if c in by_country]
    ordered.extend(item for item in results if isinstance(item, dict) and item not in ordered)
    for country in ordered:
        for release in country.get("release_dates") or []:
            if not isinstance(release, dict):
                continue
            cert = str(release.get("certification") or "").strip()
            if cert:
                code = str(country.get("iso_3166_1") or "").strip()
                return f"{code}-{cert}" if code else cert
    return ""


def _trailer_url(details: dict[str, Any]) -> str:
    videos = details.get("videos") or {}
    results = videos.get("results") if isinstance(videos, dict) else []
    if not isinstance(results, list):
        return ""
    preferred = []
    for video in results:
        if not isinstance(video, dict):
            continue
        site = str(video.get("site") or "").lower()
        typ = str(video.get("type") or "").lower()
        key = str(video.get("key") or "").strip()
        if site == "youtube" and key:
            score = 0
            if typ == "trailer":
                score += 2
            if bool(video.get("official")):
                score += 1
            preferred.append((score, key))
    if not preferred:
        return ""
    preferred.sort(reverse=True)
    return f"https://www.youtube.com/watch?v={preferred[0][1]}"
