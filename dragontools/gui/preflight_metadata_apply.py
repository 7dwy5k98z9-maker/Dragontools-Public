# -*- coding: utf-8 -*-
"""Apply an explicit metadata command plan at the widget boundary."""
from __future__ import annotations
from .preflight_metadata_commands import metadata_widget_calls


def apply_metadata_result(widget, suggestion) -> None:
    calls = metadata_widget_calls(suggestion,
        supports_online=hasattr(widget, 'apply_online_metadata_suggestion'))
    for call in calls:
        if call.optional and not hasattr(widget, call.method):
            continue
        getattr(widget, call.method)(*call.args, **call.kwargs)
