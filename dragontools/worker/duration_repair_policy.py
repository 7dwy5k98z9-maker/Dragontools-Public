# -*- coding: utf-8 -*-
from __future__ import annotations

from pathlib import Path

from .workflow_engine import WorkflowVerifyResult


def can_repair_duration(
    *,
    output_path: str | None,
    container: str,
    verify_result: WorkflowVerifyResult,
    normal_remux_enabled: bool,
    timestamp_repair_enabled: bool,
) -> bool:
    if not output_path or not (normal_remux_enabled or timestamp_repair_enabled):
        return False
    container_name = str(container or "").strip().lower().lstrip(".")
    suffix = Path(output_path).suffix.lower()
    if not (
        (container_name == "mkv" and suffix == ".mkv")
        or (container_name == "mp4" and suffix == ".mp4")
    ):
        return False
    return (
        bool(verify_result.exists)
        and bool(verify_result.size_ok)
        and bool(verify_result.container_ok)
        and bool(verify_result.probe_ok)
        and bool(verify_result.video_ok)
        and bool(verify_result.audio_ok)
        and bool(getattr(verify_result, "subtitle_ok", True))
        and bool(getattr(verify_result, "contract_ok", True))
        and bool(getattr(verify_result, "metadata_ok", True))
        and not bool(verify_result.duration_ok)
    )


def mark_duration_repair_failed(final_result, messages: list[str]) -> None:
    """Keep rejected repair candidates fail-closed for every caller."""
    final_result.duration_ok = False
    reject_message = (
        "Automatische Reparatur endgueltig verworfen; die Datei darf nicht "
        "als fertige Ausgabe uebernommen werden."
    )
    if reject_message not in messages:
        messages.append(reject_message)
    final_result.messages = messages
