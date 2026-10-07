# -*- coding: utf-8 -*-
"""Compatibility imports for the shared, Qt-free subtitle output planner."""
from ..rules.subtitle_output_plan import (
    TEXT_TO_SRT_CODECS, SidecarSelection, dedupe_stream_objects,
    select_sidecar_streams, _selected_streams,
)

__all__ = ["TEXT_TO_SRT_CODECS", "SidecarSelection", "dedupe_stream_objects", "select_sidecar_streams"]
