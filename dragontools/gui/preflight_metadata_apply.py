# -*- coding: utf-8 -*-
"""Überträgt Hintergrund-Metadatenergebnisse in die Preflight-Widgets."""
from __future__ import annotations


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
    if isinstance(suggestion, dict) and "__existing_movie_dir__" in suggestion:
        if hasattr(widget, "apply_existing_movie_dir"):
            widget.apply_existing_movie_dir(
                str(suggestion.get("__existing_movie_dir__") or ""), str(suggestion.get("base") or ""),
                str(suggestion.get("movie_name") or ""), str(suggestion.get("source") or "database"),
                str(suggestion.get("notice") or ""),
            )
        return
    if isinstance(suggestion, dict) and "__movie_library_warning__" in suggestion:
        if hasattr(widget, "apply_unusable_movie_match"):
            widget.apply_unusable_movie_match(
                message=str(suggestion.get("__movie_library_warning__") or ""),
                movie_name=str(suggestion.get("movie_name") or ""),
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
