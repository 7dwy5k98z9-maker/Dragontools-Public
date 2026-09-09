# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass

from ..core.models import SubtitleStream

@dataclass(frozen=True)
class SubtitlePlan:
    override_mode: str
    burn_sub: SubtitleStream | None
    keep_streams: tuple[SubtitleStream, ...]
    external_streams: tuple[SubtitleStream, ...]
    burn_candidates: tuple[SubtitleStream, ...] = ()
    burn_blocked_reason: str | None = None
    burn_warnings: tuple[str, ...] = ()
    burn_event_rate: float | None = None

@dataclass(frozen=True)
class MP4SubtitleStoragePlan:
    """Containerstrategie für bereits fachlich ausgewählte MP4-Untertitel.

    Textbasierte Formate können als ``mov_text`` intern gespeichert werden.
    Bildbasierte Formate (PGS/SUP, VobSub/DVD-Sub) bleiben wegen der
    Kompatibilität externe Sidecars. Ist die globale MP4-Sidecar-Option aktiv,
    werden dagegen alle ausgewählten MP4-Untertitel extern abgelegt.
    """

    internal_streams: tuple[SubtitleStream, ...]
    external_streams: tuple[SubtitleStream, ...]
