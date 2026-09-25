# -*- coding: utf-8 -*-
"""Helpers for applying the full file-settings dialog to multiple queue items."""
from __future__ import annotations

from copy import deepcopy


DIALOG_OVERRIDE_KEYS = {
    "processing_mode",
    "strip_only",
    "encoder_override",
    "audio_mode",
    "subtitle_mode",
    "audio_tracks",
    "audio_action",
    "audio_drc",
    "audio_loudnorm",
    "subtitle_tracks",
    "burn_mode",
    "burn_stream_index",
    "imax",
    "preserve_dv",
    "preserve_hdrplus",
    "sdr_hdr",
    "generate_hdr10plus",
}


def merge_dialog_override(existing: dict | None, template: dict | None) -> dict:
    """Apply only fields owned by the file-settings dialog.

    Per-file state that is intentionally not edited by this dialog (for example
    an assigned encoder profile or future queue metadata) remains untouched.
    """
    result = dict(existing or {})
    source = dict(template or {})
    for key in DIALOG_OVERRIDE_KEYS:
        if key in source:
            result[key] = deepcopy(source[key])
        else:
            result.pop(key, None)
    return result


__all__ = ["DIALOG_OVERRIDE_KEYS", "merge_dialog_override"]
