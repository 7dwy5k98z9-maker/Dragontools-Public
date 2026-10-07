# -*- coding: utf-8 -*-
"""Versionsvergleich und Auswertung der öffentlichen GitHub-Release-Antwort."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from urllib.parse import urlsplit, unquote


UPDATE_REPOSITORY = "7dwy5k98z9-maker/Dragontools-Releases"
UPDATE_API_URL = f"https://api.github.com/repos/{UPDATE_REPOSITORY}/releases/latest"
UPDATE_RELEASES_URL = f"https://github.com/{UPDATE_REPOSITORY}/releases"

_VERSION_RE = re.compile(r"^[vV]?([0-9]+(?:\.[0-9]+){1,3})(?:-([0-9A-Za-z.-]+))?(?:\+([0-9A-Za-z.-]+))?$")


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag_name: str
    title: str
    notes: str
    page_url: str
    published_at: str


@dataclass(frozen=True)
class UpdateCheckResult:
    ok: bool
    update_available: bool = False
    release: ReleaseInfo | None = None
    error: str = ""


def _parse_version(value: str) -> tuple[tuple[int, ...], str | None, str | None]:
    match = _VERSION_RE.fullmatch(str(value or "").strip())
    if match is None:
        raise ValueError(f"Ungültige Versionsnummer: {value!r}")
    core_tokens = match.group(1).split(".")
    if any(len(t) > 1 and t.startswith("0") for t in core_tokens):
        raise ValueError("Versionskern enthält führende Nullen.")
    for group in (match.group(2), match.group(3)):
        if group is not None and any(not t for t in group.split(".")):
            raise ValueError("Versionsnummer enthält leere Bezeichner.")
    if match.group(2) and any(t.isdigit() and len(t) > 1 and t.startswith("0") for t in match.group(2).split(".")):
        raise ValueError("Prerelease enthält führende Nullen.")
    parts = tuple(int(part) for part in core_tokens)
    core = parts + (0,) * (4 - len(parts))
    return core, match.group(2), match.group(3)


def version_tuple(value: str) -> tuple[int, ...]:
    """Liefert den numerischen Kern einer DragonTools-Version."""
    core, _prerelease, _build = _parse_version(value)
    return core


def _prerelease_key(value: str | None) -> tuple[tuple[int, object], ...]:
    if value is None:
        return ((2, ""),)  # stable > every prerelease with the same core
    tokens: list[tuple[int, object]] = []
    for token in value.split("."):
        if token.isdigit():
            tokens.append((0, int(token)))
        else:
            tokens.append((1, token))
    return tuple(tokens)


def _version_key(value: str) -> tuple[tuple[int, ...], int, tuple[tuple[int, object], ...]]:
    core, prerelease, _build = _parse_version(value)
    return core, 1 if prerelease is None else 0, _prerelease_key(prerelease)


def is_newer_version(candidate: str, current: str) -> bool:
    """SemVer-artiger Vergleich; Build-Metadaten beeinflussen die Reihenfolge nicht."""
    return _version_key(candidate) > _version_key(current)


def parse_release_response(payload: bytes | str, current_version: str) -> UpdateCheckResult:
    """Validiert die Antwort von GitHubs ``releases/latest``-Schnittstelle."""
    try:
        raw = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Die Release-Antwort ist kein JSON-Objekt.")

        if data.get("draft") not in (None, False) or data.get("prerelease") not in (None, False):
            raise ValueError("Die Latest-Release-Antwort ist keine öffentliche stabile Freigabe.")
        tag_name = str(data.get("tag_name") or "").strip()
        version_tuple(tag_name)
        page_url = str(data.get("html_url") or UPDATE_RELEASES_URL).strip()
        url = urlsplit(page_url)
        expected_path = f"/{UPDATE_REPOSITORY}/releases/tag/{tag_name}"
        if (url.scheme != "https" or url.netloc.casefold() != "github.com"
                or unquote(url.path).casefold() != expected_path.casefold() or url.query or url.fragment):
            page_url = UPDATE_RELEASES_URL

        release = ReleaseInfo(
            version=tag_name.lstrip("vV"),
            tag_name=tag_name,
            title=str(data.get("name") or tag_name).strip(),
            notes=str(data.get("body") or "").strip(),
            page_url=page_url,
            published_at=str(data.get("published_at") or "").strip(),
        )
        return UpdateCheckResult(
            ok=True,
            update_available=is_newer_version(release.version, current_version),
            release=release,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, TypeError, ValueError) as exc:
        return UpdateCheckResult(ok=False, error=str(exc))

