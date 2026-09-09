# -*- coding: utf-8 -*-
"""Versionsvergleich und Auswertung der öffentlichen GitHub-Release-Antwort."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass


UPDATE_REPOSITORY = "7dwy5k98z9-maker/Dragontools-Releases"
UPDATE_API_URL = f"https://api.github.com/repos/{UPDATE_REPOSITORY}/releases/latest"
UPDATE_RELEASES_URL = f"https://github.com/{UPDATE_REPOSITORY}/releases"

_VERSION_RE = re.compile(r"^[vV]?(\d+(?:\.\d+){1,3})(?:[-+].*)?$")


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


def version_tuple(value: str) -> tuple[int, ...]:
    """Wandelt ``9.8`` oder ``v9.8.1`` in einen vergleichbaren Zahlentupel um."""
    match = _VERSION_RE.fullmatch(str(value or "").strip())
    if match is None:
        raise ValueError(f"Ungültige Versionsnummer: {value!r}")
    parts = tuple(int(part) for part in match.group(1).split("."))
    return parts + (0,) * (4 - len(parts))


def is_newer_version(candidate: str, current: str) -> bool:
    return version_tuple(candidate) > version_tuple(current)


def parse_release_response(payload: bytes | str, current_version: str) -> UpdateCheckResult:
    """Validiert die Antwort von GitHubs ``releases/latest``-Schnittstelle."""
    try:
        raw = payload.decode("utf-8") if isinstance(payload, bytes) else payload
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("Die Release-Antwort ist kein JSON-Objekt.")

        tag_name = str(data.get("tag_name") or "").strip()
        version_tuple(tag_name)
        page_url = str(data.get("html_url") or UPDATE_RELEASES_URL).strip()
        if not page_url.startswith("https://github.com/"):
            page_url = UPDATE_RELEASES_URL

        release = ReleaseInfo(
            version=_VERSION_RE.fullmatch(tag_name).group(1),  # type: ignore[union-attr]
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

