# -*- coding: utf-8 -*-
"""Typed MKV track metadata editing via mkvpropedit."""
from __future__ import annotations

from pathlib import Path

from .process_runner import run_analysis_tool, tool_available
from .lang_codes import mkv_language_tags
from .timeout_settings import get_timeout


def apply_mkv_track_metadata(
    mkv_path: str,
    *,
    stream_type: str,
    ordinal: int,
    mkvpropedit_path: str,
    language: str | None = None,
    title: str | None = None,
) -> tuple[bool, str]:
    path = Path(mkv_path)
    if path.suffix.casefold() != ".mkv":
        return False, "Direkte Track-Metadatenkorrektur ist in Patch I nur für MKV aktiviert."
    kind = str(stream_type or "").strip().casefold()
    selector_prefix = {"audio": "a", "subtitle": "s"}.get(kind)
    if not selector_prefix or int(ordinal or 0) <= 0:
        return False, "Track konnte nicht eindeutig adressiert werden."
    if not tool_available(mkvpropedit_path):
        return False, "mkvpropedit wurde nicht gefunden."

    changes: list[str] = []
    if str(language or "").strip():
        legacy, ietf = mkv_language_tags(language)
        changes.append(f"language={legacy}")
        changes.append(f"language-ietf={ietf}")
    if title is not None:
        changes.append(f"name={str(title).strip()}")
    if not changes:
        return True, "Keine Track-Metadatenänderung erforderlich."

    cmd = [
        str(mkvpropedit_path),
        str(path),
        "--edit",
        f"track:{selector_prefix}{int(ordinal)}",
    ]
    for expression in changes:
        cmd.extend(["--set", expression])
    result = run_analysis_tool(
        cmd,
        allow_error=True,
        timeout=get_timeout("subtitle_tag"),
    )
    if result.returncode not in {0, 1}:
        detail = (result.stderr or result.stdout or "mkvpropedit fehlgeschlagen").strip()
        return False, detail
    if result.returncode == 1:
        return True, "mkvpropedit hat die Änderung mit Warnung angewendet."
    return True, "Track-Metadaten wurden aktualisiert."


__all__ = ["apply_mkv_track_metadata"]
