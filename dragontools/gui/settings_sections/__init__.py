# -*- coding: utf-8 -*-
"""Fachlich getrennte Bereiche des globalen Einstellungsdialogs."""
from .storage import StorageLoggingSection
from .runtime import RuntimeToolsSection
from .media import MediaPostprocessSection
from .video import VideoAnalysisSection
from .safety import SafetyValidationSection

__all__ = [
    "StorageLoggingSection",
    "RuntimeToolsSection",
    "MediaPostprocessSection",
    "VideoAnalysisSection",
    "SafetyValidationSection",
]
