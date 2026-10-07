# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field

# Separate synthetic fallback selection from every nonnegative MakeMKV title ID.
FFMPEG_FALLBACK_TITLE_ID = -1


class ISOUserAbortError(RuntimeError):
    """Raised internally when an ISO tool run was cancelled by the user."""


@dataclass(slots=True)
class ISOScanResult:
    titles: list[dict] = field(default_factory=list)
    error: str | None = None


@dataclass(slots=True)
class ISOExtractionResult:
    ok: bool
    extracted_files: list[str] = field(default_factory=list)
    error: str | None = None
