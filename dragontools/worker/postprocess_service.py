# -*- coding: utf-8 -*-
from __future__ import annotations

"""Stabile Fassade für NFO-/Trickplay-Postprocessing."""

from .postprocess_async import AsyncPostProcessCoordinator, postprocess_max_workers
from .postprocess_config import config_from_settings
from .postprocess_metadata import PostProcessMetadataSession
from .postprocess_models import NfoSettings, PostProcessConfig, PostProcessItem, PostProcessRunResult
from .postprocess_runner import PostProcessService

__all__ = [
    "NfoSettings", "PostProcessConfig", "PostProcessItem", "PostProcessRunResult",
    "config_from_settings", "PostProcessMetadataSession", "PostProcessService",
    "postprocess_max_workers", "AsyncPostProcessCoordinator",
]
