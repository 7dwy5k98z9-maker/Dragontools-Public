# -*- coding: utf-8 -*-
"""Hintergrund-Metadatensuche für den Preflight-Dialog."""
from __future__ import annotations

from collections.abc import Callable
import re
from PyQt6.QtCore import QSettings
from ..core.settings import APP_ORG, APP_NAME


def _safe_year(value) -> int | None:
    try:
        number = int(value)
    except (TypeError, ValueError):
        match = re.search(r"\((19\d{2}|20\d{2})\)\s*$", str(value or "").strip())
        return int(match.group(1)) if match else None
    return number if 1900 <= number <= 2099 else None


def _series_folder_choices(find_candidates, series_name: str, search_bases, year: int | None = None) -> list[dict]:
    for base_info in search_bases:
        if not isinstance(base_info, dict):
            continue
        base = str(base_info.get("base") or "")
        if not base:
            continue
        candidates = find_candidates(base, series_name, year=year)
        if candidates:
            base_type = str(base_info.get("type") or "")
            return [{"path": path, "base": base, "base_type": base_type} for path in candidates]
    return []


def _existing_series_payload(choice: dict, series_name: str, source: str = "folder_search", notice: str = "") -> dict:
    return {
        "__existing_series_dir__": choice.get("path", ""),
        "base": choice.get("base", ""),
        "base_type": choice.get("base_type", ""),
        "series_name": series_name,
        "source": source,
        "notice": notice,
    }


def _series_choices_payload(choices: list[dict], series_name: str, suggested_series_name: str = "") -> dict:
    return {
        "__series_dir_choices__": choices,
        "series_name": series_name,
        "suggested_series_name": suggested_series_name,
    }


def online_metadata_enabled() -> bool:
    try:
        from ..core.online_metadata import config_from_settings, metadata_provider_configured
        cfg = config_from_settings(QSettings(APP_ORG, APP_NAME), require_enabled=False)
        return metadata_provider_configured(cfg, "movie") or metadata_provider_configured(cfg, "series")
    except (ImportError, OSError, RuntimeError, TypeError, ValueError):
        return False


def run_metadata_lookup(jobs, result_queue, *, online_enabled: bool = True, is_cancelled: Callable[[], bool] | None = None) -> None:
    is_cancelled = is_cancelled or (lambda: False)
    try:
        from ..core.online_metadata import suggest_movie_metadata_for_file, suggest_series_metadata_for_name
        from ..core.media_library import find_series_dir_from_settings
        from ..rules.move_rules import find_series_dir_candidates
        settings = QSettings(APP_ORG, APP_NAME)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as exc:
        for kind, key, _payload in jobs:
            result_queue.put((kind, key, {"__error__": str(exc)}))
        result_queue.put(("done", "", None))
        return

    try:
        for kind, key, payload in jobs:
            if is_cancelled():
                break
            try:
                suggestion = None
                if kind == "movie":
                    suggestion = suggest_movie_metadata_for_file(payload, settings)
                elif kind == "series":
                    payload_info = payload if isinstance(payload, dict) else {"base": "", "series_name": str(payload)}
                    series_name = str(payload_info.get("series_name") or "").strip()
                    search_bases = payload_info.get("search_bases") or []
                    if not isinstance(search_bases, list) or not search_bases:
                        search_bases = [{"type": "", "base": str(payload_info.get("base") or "")}]
                    desired_year = _safe_year(payload_info.get("year")) or _safe_year(series_name)
                    raw_choices: list[dict] = []
                    early_suggestion = None
                    if series_name and not desired_year:
                        raw_choices = _series_folder_choices(find_series_dir_candidates, series_name, search_bases)
                        if len(raw_choices) > 1 and online_enabled:
                            early_suggestion = suggest_series_metadata_for_name(series_name, settings)
                            desired_year = _safe_year(getattr(early_suggestion, "first_air_year", None))
                    library_match = None
                    if series_name:
                        db_bases = [
                            (str(info.get("base") or ""), str(info.get("type") or ""))
                            for info in search_bases
                            if isinstance(info, dict) and str(info.get("base") or "")
                        ]
                        library_match = find_series_dir_from_settings(settings, series_name, db_bases, year=desired_year)
                    if library_match:
                        unusable = str(library_match.get("unusable_reason") or "")
                        if unusable:
                            result_queue.put((kind, key, {
                                "__library_path_warning__": unusable,
                                "base": library_match.get("base", ""),
                                "base_type": library_match.get("base_type", ""),
                                "series_name": series_name,
                                "suggested_series_name": library_match.get("suggested_series_name", ""),
                            }))
                        elif library_match.get("series_dir"):
                            note = str(library_match.get("mapping_notice") or "").strip() or (
                                "DB-Pfad entspricht dem aktuell konfigurierten Speicherpfad und wurde vor dem Verschieben geprüft."
                            )
                            result_queue.put((kind, key, {
                                "__existing_series_dir__": library_match.get("series_dir", ""),
                                "base": library_match.get("base", ""),
                                "base_type": library_match.get("base_type", ""),
                                "series_name": series_name,
                                "source": library_match.get("source", "database"),
                                "notice": note,
                            }))
                            continue
                    if series_name:
                        choices = _series_folder_choices(
                            find_series_dir_candidates, series_name, search_bases, desired_year
                        ) if desired_year else []
                        if len(choices) == 1:
                            result_queue.put((kind, key, _existing_series_payload(choices[0], series_name)))
                            continue
                        if len(choices) > 1:
                            result_queue.put((kind, key, _series_choices_payload(choices, series_name)))
                            continue
                        raw_choices = raw_choices or _series_folder_choices(
                            find_series_dir_candidates, series_name, search_bases
                        )
                        if len(raw_choices) == 1:
                            result_queue.put((kind, key, _existing_series_payload(raw_choices[0], series_name)))
                            continue
                        if len(raw_choices) > 1 and online_enabled:
                            suggestion = early_suggestion or suggest_series_metadata_for_name(series_name, settings)
                            suggestion_year = _safe_year(getattr(suggestion, "first_air_year", None))
                            suggested_name = str(getattr(suggestion, "folder_name", "") or "")
                            if suggestion_year:
                                choices = _series_folder_choices(
                                    find_series_dir_candidates, series_name, search_bases, suggestion_year
                                ) or _series_folder_choices(
                                    find_series_dir_candidates, suggested_name, search_bases, suggestion_year
                                )
                                if len(choices) == 1:
                                    result_queue.put((kind, key, _existing_series_payload(choices[0], series_name)))
                                    continue
                                if len(choices) > 1:
                                    result_queue.put((kind, key, _series_choices_payload(choices, series_name, suggested_name)))
                                    continue
                            result_queue.put((kind, key, _series_choices_payload(raw_choices, series_name, suggested_name)))
                            continue
                        if len(raw_choices) > 1:
                            result_queue.put((kind, key, _series_choices_payload(raw_choices, series_name)))
                            continue
                    suggestion = suggest_series_metadata_for_name(series_name, settings) if online_enabled else {"__local_series_missing__": True}
                result_queue.put((kind, key, suggestion))
            except Exception as exc:  # Provider-/DB-Grenze: Fehler wird als Ergebnis an die GUI transportiert.
                result_queue.put((kind, key, {"__error__": str(exc)}))
    finally:
        result_queue.put(("done", "", None))


def apply_metadata_result(widget, suggestion) -> None:
    if isinstance(suggestion, dict) and "__error__" in suggestion:
        if hasattr(widget, "mark_metadata_lookup_failed"):
            widget.mark_metadata_lookup_failed(str(suggestion.get("__error__") or ""))
        return
    if isinstance(suggestion, dict) and "__existing_series_dir__" in suggestion:
        if hasattr(widget, "apply_existing_series_dir"):
            widget.apply_existing_series_dir(
                str(suggestion.get("__existing_series_dir__") or ""),
                str(suggestion.get("base") or ""), str(suggestion.get("series_name") or ""),
                str(suggestion.get("base_type") or ""), str(suggestion.get("source") or "folder_search"),
                str(suggestion.get("notice") or ""),
            )
        return
    if isinstance(suggestion, dict) and "__library_path_warning__" in suggestion:
        if hasattr(widget, "apply_unusable_library_series_match"):
            widget.apply_unusable_library_series_match(
                message=str(suggestion.get("__library_path_warning__") or ""),
                series_name=str(suggestion.get("series_name") or ""),
                suggested_series_name=str(suggestion.get("suggested_series_name") or ""),
                base=str(suggestion.get("base") or ""), base_type=str(suggestion.get("base_type") or ""),
            )
        return
    if isinstance(suggestion, dict) and "__series_dir_choices__" in suggestion:
        if hasattr(widget, "apply_existing_series_dir_choices"):
            widget.apply_existing_series_dir_choices(
                choices=list(suggestion.get("__series_dir_choices__") or []),
                series_name=str(suggestion.get("series_name") or ""),
                suggested_series_name=str(suggestion.get("suggested_series_name") or ""),
            )
        return
    if isinstance(suggestion, dict) and "__local_series_missing__" in suggestion:
        if hasattr(widget, "mark_existing_series_dir_not_found"):
            widget.mark_existing_series_dir_not_found()
        return
    widget.apply_online_metadata_suggestion(suggestion)
