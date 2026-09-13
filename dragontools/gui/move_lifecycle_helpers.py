# -*- coding: utf-8 -*-
from __future__ import annotations


def merge_restored_target_paths(paths: dict, restored_context: dict) -> dict:
    """Übernimmt nur explizit persistierte Zielpfade in eine frische Pfadkopie."""
    merged = dict(paths or {})
    restored = restored_context.get("target_paths")
    if not isinstance(restored, dict):
        return merged
    for key in ("tv", "anime", "film"):
        value = str(restored.get(key) or "")
        if value:
            merged[key] = value
    return merged


def format_move_eta(eta_s: float) -> str:
    if eta_s < 0:
        return ""
    if eta_s < 60:
        return f"Verschieben – noch ca. {int(eta_s)} s"
    if eta_s < 3600:
        minutes, seconds = divmod(int(eta_s), 60)
        return f"Verschieben – noch ca. {minutes} min {seconds:02d} s"
    hours, remainder = divmod(int(eta_s), 3600)
    minutes = remainder // 60
    return f"Verschieben – noch ca. {hours} h {minutes:02d} min"


def retire_move_thread(state, move_thread) -> None:
    if move_thread is None:
        return
    retired = getattr(state, "retired_move_threads", None)
    if retired is None:
        return
    if move_thread not in retired:
        retired.append(move_thread)
    del retired[:-8]


def successful_video_sources(move_log: list) -> set[str]:
    moved: set[str] = set()
    for entry in move_log or []:
        if not isinstance(entry, dict):
            continue
        if entry.get("kind", "video") != "video" or not entry.get("ok"):
            continue
        source = str(entry.get("source_path") or "")
        if source:
            moved.add(source)
    return moved


def input_paths_for_output(run_results: dict, output_path: str) -> list[str]:
    inputs = [
        input_path
        for input_path, result in (run_results or {}).items()
        if isinstance(result, dict) and result.get("output_path") == output_path
    ]
    if not inputs and output_path:
        inputs.append(output_path)
    return inputs
