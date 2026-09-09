# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class WorkerRuntimeState:
    total_before: int = 0
    total_after: int = 0
    erfolgreich: int = 0
    fehlgeschlagen: int = 0
    current_idx: int = 0
    total_count: int = 0
