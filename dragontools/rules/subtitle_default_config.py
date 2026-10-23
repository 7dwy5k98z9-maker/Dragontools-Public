"""Normalization for configurable default subtitle selection (no I/O)."""
from __future__ import annotations

from ..core.lang_codes import canonical_lang, normalize_language_priority


def normalize_default_subtitle(raw, *, language_priority=None):
    """Absent settings retain the previous automatic policy until edited."""
    if not isinstance(raw, dict):
        return {
            "mode": "legacy",
            "audio_language": "audio_priority",
            "language_priority": normalize_language_priority(language_priority or ["de", "en"]),
        }
    mode = str(raw.get("mode", "preserve")).strip().lower()
    if mode not in {"always", "audio_differs", "preserve", "legacy"}:
        mode = "preserve"
    language = raw.get("audio_language", "de")
    language = "audio_priority" if language == "audio_priority" else canonical_lang(language)
    if language in {"", "und", "mul", "zxx"}:
        language = "de"
    priority = normalize_language_priority(raw.get("language_priority", language_priority or ["de", "en"]))
    return {"mode": mode, "audio_language": language, "language_priority": priority}
